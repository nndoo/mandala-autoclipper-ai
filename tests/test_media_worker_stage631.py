"""Offline API compatibility checks against the byte-matched VPS source."""

import hashlib
import http.client
import importlib.util
import json
import os
import sys
import tempfile
import threading
import types
import unittest
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'backend/vps_snapshot/worker.py'
EXPECTED_SHA256 = '718d15e45ad4fb24935e65e6bc227ac7b3bd12e1b070844c24aecf9120c5e975'


def load_worker_modules():
    if 'psycopg' not in sys.modules:
        fake_psycopg = types.ModuleType('psycopg')
        fake_psycopg.Error = type('PsycopgError', (Exception,), {})
        sys.modules['psycopg'] = fake_psycopg
    spec = importlib.util.spec_from_file_location('vps_worker_snapshot', SNAPSHOT)
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    from backend.media_worker import app as local
    return original, local


def request(handler, method, path, payload=None):
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        body = json.dumps(payload).encode() if payload is not None else None
        conn.request(method, path, body=body,
                     headers={'Content-Type': 'application/json'} if body else {})
        response = conn.getresponse()
        result = response.status, response.getheader('Content-Type'), response.read()
        conn.close()
        return result
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


class MediaWorkerStage631Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original, cls.local = load_worker_modules()

    def test_vps_snapshot_sha256(self):
        self.assertEqual(hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest(), EXPECTED_SHA256)

    def test_defaults_match_vps(self):
        for name in ('USERNAME', 'CHANNEL_ID', 'ROOT', 'MAX_BYTES'):
            self.assertEqual(getattr(self.original, name), getattr(self.local, name))

    def test_health_and_unknown_path(self):
        for method, path in [('GET', '/health'), ('GET', '/missing'), ('POST', '/missing')]:
            with self.subTest(method=method, path=path):
                self.assertEqual(request(self.original.Handler, method, path),
                                 request(self.local.Handler, method, path))

    def test_discover_contract(self):
        cases = [
            {'username': 'wrong', 'maxVideos': 1},
            {'username': self.original.USERNAME, 'maxVideos': 11},
            {'username': self.original.USERNAME, 'maxVideos': 2},
        ]
        result = types.SimpleNamespace(
            returncode=0,
            stdout=json.dumps({'entries': [
                {'id': '1234567890123456789', 'title': 'clip'},
                {'id': 'invalid', 'title': 'ignored'},
            ]}),
        )
        for payload in cases:
            with self.subTest(payload=payload), mock.patch('subprocess.run', return_value=result):
                self.assertEqual(request(self.original.Handler, 'POST', '/source/discover', payload),
                                 request(self.local.Handler, 'POST', '/source/discover', payload))

    def test_download_and_file_admission(self):
        claim = '01234567-89ab-cdef-0123-456789abcdef'
        for path in ('/source/download', '/source/file'):
            for payload in (
                {'videoId': 'bad', 'claimToken': claim},
                {'videoId': '1234567890123456789', 'claimToken': 'bad'},
                {'videoId': '1234567890123456789', 'claimToken': claim},
            ):
                with self.subTest(path=path, payload=payload), mock.patch.dict(os.environ, {
                    'PGHOST': '', 'PGUSER': '', 'PGPASSWORD': '',
                }):
                    self.assertEqual(request(self.original.Handler, 'POST', path, payload),
                                     request(self.local.Handler, 'POST', path, payload))

    def test_file_stream_success(self):
        video_id = '1234567890123456789'
        payload = {'videoId': video_id, 'claimToken': '01234567-89ab-cdef-0123-456789abcdef'}
        with tempfile.TemporaryDirectory() as tmp:
            originals = Path(tmp)
            media = b'X' * 1024
            (originals / f'{video_id}.mp4').write_bytes(media)
            sha = hashlib.sha256(media).hexdigest()
            actual = []
            for module in (self.original, self.local):
                with mock.patch.object(module, 'ORIGINALS', originals), mock.patch.object(
                    module, 'verify_original_access', return_value=(len(media), sha)
                ):
                    actual.append(request(module.Handler, 'POST', '/source/file', payload))
            self.assertEqual(actual[0], actual[1])
            self.assertEqual(actual[0][0], 200)
            self.assertEqual(actual[0][2], media)

    def test_existing_download_success(self):
        video_id = '1234567890123456789'
        payload = {'videoId': video_id, 'claimToken': '01234567-89ab-cdef-0123-456789abcdef'}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            originals = root / 'originals'
            originals.mkdir()
            (originals / f'{video_id}.mp4').write_bytes(b'X' * 1024)
            actual = []
            conn = mock.MagicMock()
            conn.__enter__.return_value = conn
            for module in (self.original, self.local):
                with ExitStack() as stack:
                    stack.enter_context(mock.patch.object(module, 'ORIGINALS', originals))
                    stack.enter_context(mock.patch.object(module, 'TEMP', root / 'tmp'))
                    stack.enter_context(mock.patch.object(module, 'LOCKS', root / 'locks'))
                    stack.enter_context(mock.patch.object(module, 'verify_claim', return_value=conn))
                    stack.enter_context(mock.patch.object(module, 'describe_media', return_value={
                        'sizeBytes': 1024, 'sha256': 'a' * 64,
                    }))
                    actual.append(request(module.Handler, 'POST', '/source/download', payload))
            self.assertEqual(actual[0], actual[1])
            self.assertEqual(actual[0][0], 200)
            self.assertTrue(json.loads(actual[0][2])['alreadyExists'])


if __name__ == '__main__':
    unittest.main()
