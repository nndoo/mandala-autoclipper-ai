"""Stage 3 original intake: real offline MP4 plus negative contract tests."""

import copy
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.media_worker import intake_adapter as intake
from validate_universal_analysis_v02 import sample_analysis

PROJECT = Path(__file__).resolve().parents[1]


class IntakeAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='mandala-stage632-')
        cls.root = Path(cls.temporary.name) / 'source'
        schemas = cls.root.parent / 'src' / 'schemas'
        schemas.mkdir(parents=True)
        shutil.copyfile(PROJECT / 'src/schemas/adaptive-director-input.v0.3.schema.json',
                        schemas / 'adaptive-director-input.v0.3.schema.json')
        originals = cls.root / 'originals'
        originals.mkdir(parents=True)
        cls.video_id = '1234567890123456789'
        cls.video = originals / f'{cls.video_id}.mp4'
        subprocess.run([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
            '-i', 'testsrc2=size=320x480:rate=30000/1001', '-t', '1.2',
            '-c:v', 'mpeg4', '-q:v', '10', '-y', str(cls.video),
        ], check=True, timeout=30)
        cls.probed = intake.stage5.probe_video(cls.video)
        cls.digest = hashlib.sha256(cls.video.read_bytes()).hexdigest()
        cls.record = {
            'source_key': f'tiktok:{cls.video_id}',
            'platform': 'tiktok',
            'username': intake.USERNAME,
            'video_id': cls.video_id,
            'status': 'ORIGINAL_READY',
            'original_local_path': str(cls.video),
            'original_size_bytes': cls.video.stat().st_size,
            'original_sha256': cls.digest,
            'original_duration_seconds': cls.probed['duration_sec'],
            'original_width': cls.probed['width'],
            'original_height': cls.probed['height'],
        }

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def prepare(self, **changes):
        record = copy.deepcopy(self.record)
        record.update(changes)
        return intake.prepare_intake(record, storage_root=self.root)

    def blocked(self, fragment, **changes):
        with self.assertRaisesRegex(intake.IntakeError, fragment):
            self.prepare(**changes)

    def test_real_original_builds_stage5_sidecar_without_copy(self):
        before = self.video.stat()
        listing = set(self.root.rglob('*'))
        result = self.prepare()
        source = result['source']
        self.assertEqual(source, {
            'video_id': 'local-sha256-' + self.digest[:32], **self.probed,
        })
        self.assertEqual(result['metadata']['verification'], {
            'method': 'ffprobe_and_sha256', 'file_name': self.video.name,
            'sha256': self.digest,
        })
        self.assertEqual(result['original_path'], str(self.video))
        self.assertEqual((self.video.stat().st_ino, self.video.stat().st_size),
                         (before.st_ino, before.st_size))
        self.assertEqual(set(self.root.rglob('*')), listing)

    def test_duplicate_is_deterministic_and_does_not_duplicate_media(self):
        first = self.prepare()
        second = self.prepare()
        self.assertEqual(first, second)
        self.assertEqual(list((self.root / 'originals').glob('*.mp4')), [self.video])
        self.blocked('identity', source_key='tiktok:9999999999999999999')

    def test_hash_and_size_mismatch(self):
        self.blocked('SHA-256 mismatch', original_sha256='0' * 64)
        self.blocked('size differs', original_size_bytes=self.record['original_size_bytes'] - 1)

    def test_poc_limits_before_probe(self):
        with mock.patch.object(intake.stage5, 'probe_video') as probe:
            self.blocked('size limit', original_size_bytes=intake.MAX_POC_BYTES + 1)
            self.blocked('duration limit', original_duration_seconds=181)
            probe.assert_not_called()

    def test_stage3_identity_status_and_path(self):
        self.blocked('identity', status='RESERVED')
        self.blocked('identity', username='another-account')
        self.blocked('path', original_local_path='/tmp/not-the-original.mp4')
        self.blocked('video_id', video_id='../escape')

    def test_probe_duration_resolution_and_fps(self):
        self.blocked('duration or resolution', original_duration_seconds=2.0)
        self.blocked('duration or resolution', original_width=321)
        self.blocked('FPS', fps=25)
        self.assertEqual(self.prepare(fps=self.probed['fps'])['source']['fps'],
                         self.probed['fps'])

    def test_stage5_schema_and_verifier_reused(self):
        with mock.patch.object(intake.stage5, 'verify_source',
                               wraps=intake.stage5.verify_source) as verifier:
            result = self.prepare()
        verifier.assert_called_once()
        schema = intake.stage5.load_schema('adaptive-director-input.v0.3.schema.json')
        intake.stage5.validate_object(result['source'], schema['properties']['source'],
                                      'Stage 5 source')

    def test_trusted_existing_mirror_keeps_stage3_path_binding(self):
        record = copy.deepcopy(self.record)
        record['original_local_path'] = f'/data/source/originals/{self.video_id}.mp4'
        result = intake.prepare_intake(record, storage_root='/data/source',
                                       verified_mirror_path=self.video)
        self.assertEqual(result['original_path'], str(self.video))
        self.assertEqual(result['stage3_original_path'], record['original_local_path'])
        record['original_local_path'] = '/data/source/originals/wrong.mp4'
        with self.assertRaisesRegex(intake.IntakeError, 'path does not match'):
            intake.prepare_intake(record, storage_root='/data/source',
                                  verified_mirror_path=self.video)

    def test_stage5_alias_requires_same_inode(self):
        with mock.patch.object(intake.stage5, 'ROOT', self.root.parent):
            result = intake.prepare_intake(self.record, storage_root=self.root,
                                           stage5_video_path=self.video)
            self.assertEqual(result['stage5_video_path'], str(self.video))
            other = self.root.parent / 'different.mp4'
            other.write_bytes(b'not the original')
            try:
                with self.assertRaisesRegex(intake.IntakeError, 'same original file'):
                    intake.prepare_intake(self.record, storage_root=self.root,
                                          stage5_video_path=other)
            finally:
                other.unlink()

    def test_canonical_analysis_evidence_gate(self):
        result = self.prepare()
        analysis = sample_analysis()
        analysis['source'] = copy.deepcopy(result['source'])
        analysis['segments'][0]['end_sec'] = result['source']['duration_sec']
        analysis['editing_opportunities'] = []
        warnings = intake.validate_canonical_analysis(result, analysis)
        self.assertIn('Schema validation does not verify audiovisual facts or frame-accurate timing',
                      warnings)
        analysis['source']['video_id'] = 'wrong-source'
        with self.assertRaisesRegex(intake.IntakeError, 'source metadata mismatch'):
            intake.validate_canonical_analysis(result, analysis)
        analysis['source'] = copy.deepcopy(result['source'])
        analysis['segments'][0]['end_sec'] = result['source']['duration_sec'] + 1
        with self.assertRaisesRegex(intake.IntakeError, 'validation blocked'):
            intake.validate_canonical_analysis(result, analysis)


if __name__ == '__main__':
    unittest.main()
