"""Editing service isolation and startup gates; no Docker, DB or provider calls."""

import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend import editing_worker as app
from backend import runtime_check as check


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(Path, 'is_dir', return_value=True))
        self.stack.enter_context(patch.object(Path, 'is_symlink', return_value=False))
        self.stack.enter_context(patch.object(os, 'access', return_value=True))
        self.stat = self.stack.enter_context(patch.object(os, 'statvfs', side_effect=lambda p:
            SimpleNamespace(f_flag=0 if p == check.OUTPUT_ROOT else os.ST_RDONLY)))
        self.same = self.stack.enter_context(patch.object(os.path, 'samefile', side_effect=lambda a, b:
            a == check.ORIGINALS and b == check.SOURCE_ALIAS))
        self.write = self.stack.enter_context(patch.object(check.tempfile, 'TemporaryFile'))

    def test_only_editing_volume_receives_write_probe(self):
        self.assertEqual(check.inspect_storage(), [])
        self.write.assert_called_once_with(dir=check.OUTPUT_ROOT)

    def test_readwrite_original_is_blocked_without_any_write(self):
        self.stat.side_effect = lambda p: SimpleNamespace(f_flag=0)
        self.assertIn('Original storage must be mounted read-only', check.inspect_storage())
        self.write.assert_not_called()

    def test_wrong_alias_is_blocked(self):
        self.same.side_effect = None
        self.same.return_value = False
        self.assertIn('Stage 3 and Stage 5 original paths are not the same directory', check.inspect_storage())
        self.write.assert_not_called()

    def test_reused_original_volume_for_output_is_blocked(self):
        self.same.side_effect = lambda a, b: True
        self.assertIn('Editing output must use a separate volume', check.inspect_storage())
        self.write.assert_not_called()

    def test_readonly_output_is_blocked(self):
        self.stat.side_effect = lambda p: SimpleNamespace(f_flag=os.ST_RDONLY)
        self.assertIn('Editing output volume is read-only', check.inspect_storage())
        self.write.assert_not_called()


class ServiceTests(unittest.TestCase):
    def test_health_is_editing_only_and_source_job_routes_are_absent(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with urllib.request.urlopen(base + '/health', timeout=5) as response:
                data = json.load(response)
            self.assertEqual(data['service'], 'mandala-ai-editing-worker')
            self.assertFalse(data['roles_ready'])
            for path in ('/source/discover', '/source/download', '/source/file', '/v1/jobs'):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(urllib.request.Request(base + path, data=b'{}'), timeout=5)
                self.assertEqual(error.exception.code, 404)
                error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_failed_preflight_does_not_open_http_service(self):
        with patch.object(app, 'inspect', return_value={'status': 'BLOCKED'}), \
                patch.object(app, 'ThreadingHTTPServer') as server, patch('builtins.print'):
            with self.assertRaises(SystemExit):
                app.main()
            server.assert_not_called()


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            'MANDALA_OPENCLAW_PROVIDER_ID': 'test-provider', 'MANDALA_EDITING_PORT': '3003',
            'AUTOCLIPPER_SOURCE_ROOT': '/data/source',
        }, clear=True))
        self.stack.enter_context(patch.object(check.importlib.metadata, 'version',
                                             side_effect=lambda name: check.PACKAGES[name]))
        self.imports = self.stack.enter_context(patch.object(check.importlib, 'import_module'))
        self.stack.enter_context(patch.object(check.shutil, 'which', return_value='/usr/bin/test'))
        self.stack.enter_context(patch.object(Path, 'is_file', return_value=True))
        self.stack.enter_context(patch.object(Path, 'read_text', return_value=json.dumps({
            'contracts': {'mediaUnderstandingProviders': ['test-provider']}})))

    def test_runtime_preflight_needs_no_db_or_provider_secret(self):
        self.assertEqual(check.inspect(require_service_env=True)['status'], 'PASS')
        self.assertEqual(self.imports.call_count, len(check.PACKAGES))

    def test_binary_dependency_import_error_blocks_runtime(self):
        self.imports.side_effect = OSError('unavailable shared library')
        result = check.inspect(require_service_env=True)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('numpy cannot be imported', result['errors'])

    def test_port_mismatch_and_provider_binding_mismatch_are_blocked(self):
        with patch.dict(os.environ, {'MANDALA_EDITING_PORT': '3002',
                                     'MANDALA_OPENCLAW_PROVIDER_ID': 'wrong-provider'}):
            result = check.inspect(require_service_env=True)
        self.assertIn('MANDALA_EDITING_PORT must be 3003', result['errors'])
        self.assertIn('9Router provider ID differs from image manifest', result['errors'])


if __name__ == '__main__':
    unittest.main()
