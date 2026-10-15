"""PostgreSQL 16 + synthetic media + injected replay; never invoke live providers."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg.conninfo import conninfo_to_dict

from backend.editing_dispatch import Dispatcher
from backend.editing_store import EditingStore, apply_migration
from backend.roles import Stage5RoleExecutor
from backend.roles.provider import TestOnlyReplayProvider
from backend.source_admission import SourceAdmission

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


class Stage635RolesIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.getenv('MANDALA_STAGE635_TEST_ADMIN_DSN')
        if not cls.dsn:
            raise unittest.SkipTest('Isolated PostgreSQL 16 DSN not supplied')
        fields = conninfo_to_dict(cls.dsn)
        if fields.get('host') != '127.0.0.1' or fields.get('dbname') != 'mandala_stage635_test':
            raise RuntimeError('Refusing non-isolated PostgreSQL DSN')
        with psycopg.connect(cls.dsn) as conn:
            version = int(conn.execute('SHOW server_version_num').fetchone()[0])
        if not 160000 <= version < 170000:
            raise RuntimeError('PostgreSQL 16 required')
        apply_migration(cls.dsn)
        cls.test_root = ROOT / 'data' / ('stage635-test-only-' + uuid.uuid4().hex)
        cls.source_root = cls.test_root / 'source'
        (cls.source_root / 'originals').mkdir(parents=True)
        cls.addClassCleanup(lambda: shutil.rmtree(cls.test_root))
        cls.output_root = ROOT / 'data/revisions/stage59/automatic'
        cls.output_root.mkdir(parents=True, exist_ok=True)
        import run_automatic_editing_v01 as workflow
        proof_dir = cls.output_root / ('capabilities-stage635-test-only-' + uuid.uuid4().hex)
        workflow.proof(proof_dir)
        cls.proof = proof_dir / 'proof.json'
        workflow.check_proof(workflow.reference(cls.proof))
        cls.addClassCleanup(lambda: shutil.rmtree(proof_dir))
        fixture_dir = workflow.core.TEST_ROOT / (proof_dir.name + '-automatic')
        cls.addClassCleanup(lambda: shutil.rmtree(fixture_dir))
        cls.video_id = '9' + str(uuid.uuid4().int % 10**18).zfill(18)
        cls.source_key = 'tiktok:' + cls.video_id
        cls.video = cls.source_root / 'originals' / (cls.video_id + '.mp4')
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
            '-i', 'testsrc2=size=320x480:rate=30', '-f', 'lavfi', '-i',
            'sine=frequency=440:sample_rate=48000', '-t', '4', '-c:v', 'mpeg4',
            '-q:v', '10', '-c:a', 'aac', '-shortest', str(cls.video)],
            check=True, timeout=60)
        from backend.media_worker.intake_adapter import stage5
        cls.media = stage5.probe_video(cls.video)
        cls.sha = hashlib.sha256(cls.video.read_bytes()).hexdigest()
        cls.speech_video_id = '8' + str(uuid.uuid4().int % 10**18).zfill(18)
        cls.speech_source_key = 'tiktok:' + cls.speech_video_id
        cls.speech_video = cls.source_root / 'originals' / (cls.speech_video_id + '.mp4')
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
            '-i', 'testsrc2=size=320x480:rate=30', '-f', 'lavfi',
            '-i', 'flite=text=one two three:voice=slt', '-filter_complex',
            '[1:a]apad=pad_dur=4[a]', '-map', '0:v', '-map', '[a]', '-t', '4',
            '-c:v', 'mpeg4', '-q:v', '10', '-c:a', 'aac', '-shortest',
            str(cls.speech_video)], check=True, timeout=60)
        cls.speech_media = stage5.probe_video(cls.speech_video)
        cls.speech_sha = hashlib.sha256(cls.speech_video.read_bytes()).hexdigest()
        with psycopg.connect(cls.dsn) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS public.source_videos (
                source_key text PRIMARY KEY, platform text NOT NULL,
                username text NOT NULL, video_id text NOT NULL, status text NOT NULL,
                original_local_path text NOT NULL, original_size_bytes bigint NOT NULL,
                original_sha256 text NOT NULL, original_duration_seconds numeric NOT NULL,
                original_width integer NOT NULL, original_height integer NOT NULL)''')
            conn.execute('''INSERT INTO public.source_videos
                (source_key, platform, username, video_id, status, original_local_path,
                 original_size_bytes, original_sha256, original_duration_seconds,
                 original_width, original_height)
                VALUES (%s, 'tiktok', 'mandala.auto.kediri', %s, 'ORIGINAL_READY',
                        %s, %s, %s, %s, %s, %s)''',
                (cls.source_key, cls.video_id, str(cls.video), cls.video.stat().st_size,
                 cls.sha, cls.media['duration_sec'], cls.media['width'], cls.media['height']))
            conn.execute('''INSERT INTO public.source_videos
                (source_key, platform, username, video_id, status, original_local_path,
                 original_size_bytes, original_sha256, original_duration_seconds,
                 original_width, original_height)
                VALUES (%s, 'tiktok', 'mandala.auto.kediri', %s, 'ORIGINAL_READY',
                        %s, %s, %s, %s, %s, %s)''',
                (cls.speech_source_key, cls.speech_video_id, str(cls.speech_video),
                 cls.speech_video.stat().st_size, cls.speech_sha,
                 cls.speech_media['duration_sec'], cls.speech_media['width'],
                 cls.speech_media['height']))
        cls.addClassCleanup(cls._clean_source)

    @classmethod
    def _clean_source(cls):
        with psycopg.connect(cls.dsn) as conn:
            conn.execute('DELETE FROM public.source_videos WHERE source_key = %s',
                         (cls.source_key,))
            conn.execute('DELETE FROM public.source_videos WHERE source_key = %s',
                         (cls.speech_source_key,))

    def setUp(self):
        from validate_universal_analysis_v02 import sample_analysis
        if self._testMethodName.startswith('test_speech'):
            self.source_key = self.speech_source_key
            self.video = self.speech_video
            self.media = self.speech_media
            self.sha = self.speech_sha
        analysis = sample_analysis()
        if self._testMethodName.startswith('test_speech'):
            analysis['content_profile'].update(speech_presence='present', music_presence='absent')
            analysis['segments'][0].update(
                audio_description='Synthetic spoken words one two three',
                audio_layers=['speech'])
        analysis['source'] = {'video_id': 'local-sha256-' + self.sha[:32], **self.media}
        analysis['segments'][0]['end_sec'] = self.media['duration_sec']
        analysis['editing_opportunities'][0].update(start_sec=.5, end_sec=2.5)
        self.provider = TestOnlyReplayProvider({'analyst': [json.dumps(analysis)]})
        self.store = EditingStore(self.dsn, output_root=self.output_root)
        self.admission = SourceAdmission(self.dsn, self.store,
                                         storage_root=self.source_root)
        self.executor = Stage5RoleExecutor(self.store, self.admission,
                                           provider=self.provider, proof=self.proof)
        self.dispatch = Dispatcher(self.store, self.admission, executor=self.executor,
                                   ready=lambda: True)
        request = {'contract_version': 'stage6.3.5-v1', 'source_key': self.source_key,
                   'expected_sha256': self.sha}
        self.job, _ = self.admission.admit(request, principal='workflow',
                                           key='test-only-' + uuid.uuid4().hex)
        self.job_id = self.job['id']
        self.addCleanup(self._cleanup_job)
        self.store.approve_paid_inference(self.job_id)

    def _cleanup_job(self):
        with psycopg.connect(self.dsn) as conn:
            for table in ('idempotency_keys', 'job_events', 'artifacts', 'call_reservations',
                          'permits', 'tasks', 'jobs'):
                if table == 'idempotency_keys':
                    conn.execute('DELETE FROM mandala_engine.idempotency_keys WHERE job_id = %s '
                                 'OR task_id IN (SELECT id FROM mandala_engine.tasks WHERE job_id = %s)',
                                 (self.job_id, self.job_id))
                elif table == 'jobs':
                    conn.execute('DELETE FROM mandala_engine.jobs WHERE id = %s',
                                 (self.job_id,))
                else:
                    conn.execute(f'DELETE FROM mandala_engine.{table} WHERE job_id = %s',
                                 (self.job_id,))
        shutil.rmtree(self.output_root / str(self.job_id), ignore_errors=True)

    def step(self):
        job = self.store.get_job(self.job_id)
        action = job['next_action']
        self.assertIsNotNone(action)
        task, _ = self.store.submit_task(self.job_id, principal='workflow',
            key='test-only-task-' + uuid.uuid4().hex,
            expected_version=job['version'], role=action['role'], phase=action['phase'],
            attempt=action['attempt'], input_artifact_ids=action['input_artifact_ids'],
            regions=action.get('regions'))
        self.assertEqual(self.dispatch.run_once(), task['id'])
        return self.store.get_task(task['id'])

    def _free_until_director(self):
        analyst = self.step()
        self.assertEqual(analyst['state'], 'SUCCEEDED', analyst)
        self.assertEqual(self.step()['state'], 'SUCCEEDED')  # Controller
        av = self.step()
        self.assertEqual(av['state'], 'SUCCEEDED', av)
        self.assertEqual(self.step()['state'], 'SUCCEEDED')
        speech = self.step()
        self.assertEqual(speech['state'], 'SUCCEEDED', speech)
        self.assertEqual(self.step()['state'], 'SUCCEEDED')
        self.assertEqual(self.store.get_job(self.job_id)['next_action']['role'], 'director')

    def test_analyst_av_speech_free_path(self):
        self._free_until_director()

    def test_ambiguous_provider_outcome_requires_reconciliation(self):
        self.provider.replies['analyst'] = [RuntimeError('TEST_ONLY ambiguous transport')]
        task = self.step()
        self.assertEqual((task['state'], task['failure_class']),
                         ('RECONCILIATION_REQUIRED', 'EXECUTOR_UNCERTAIN'))
        self.assertEqual(self.store.get_job(self.job_id)['state'],
                         'RECONCILIATION_REQUIRED')
        rows = self.store.reservation_rows(self.job_id)
        self.assertEqual([(r['kind'], r['state']) for r in rows],
                         [('analyst', 'OUTCOME_UNKNOWN')])
        self.assertIsNone(self.dispatch.run_once())

    def test_source_mutation_blocks_role_before_provider(self):
        original = self.video.read_bytes()
        self.addCleanup(lambda: self.video.write_bytes(original))
        self.video.write_bytes(original + b'TEST_ONLY mutation')
        task = self.step()
        self.assertEqual((task['state'], task['failure_class']),
                         ('RECONCILIATION_REQUIRED', 'SOURCE_CHANGED'))
        self.assertEqual(self.store.reservation_rows(self.job_id), [])

    def test_registered_artifact_mismatch_quarantines_job(self):
        self.assertEqual(self.step()['state'], 'SUCCEEDED')
        path = self.output_root / str(self.job_id) / 'source-metadata.json'
        path.write_bytes(path.read_bytes() + b'TEST_ONLY mismatch')
        self.dispatch.recover_once()
        self.assertEqual(self.store.get_job(self.job_id)['state'],
                         'RECONCILIATION_REQUIRED')

    def test_invalid_director_response_consumes_one_budget_slot(self):
        self._free_until_director()
        self.provider.replies['director'] = ['{"invalid": true}']
        self.assertEqual(self.step()['state'], 'BLOCKED')
        self.assertEqual(self.step()['state'], 'SUCCEEDED')  # Controller
        action = self.store.get_job(self.job_id)['next_action']
        self.assertEqual((action['role'], action['attempt']), ('director', 2))
        self.assertEqual(sum(r['kind'] == 'director' for r in
                             self.store.reservation_rows(self.job_id)), 1)

    def test_validator_rejection_stops_before_permit(self):
        import run_automatic_editing_v01 as workflow
        from test_automatic_editing_v01 import proposal

        self._free_until_director()
        candidate = proposal(workflow.read(self.output_root / str(self.job_id) / 'packet.json'))
        candidate['overlays'][0]['text'] = 'KONDISI PRIMA'
        self.provider.replies['director'] = [json.dumps(candidate)]
        self.assertEqual(self.step()['state'], 'SUCCEEDED')
        self.assertEqual(self.step()['state'], 'SUCCEEDED')  # Controller
        self.assertEqual(self.step()['state'], 'BLOCKED')  # Validator
        self.assertEqual(self.step()['state'], 'SUCCEEDED')  # Controller
        action = self.store.get_job(self.job_id)['next_action']
        self.assertEqual((action['role'], action['attempt']), ('director', 2))
        with psycopg.connect(self.dsn) as conn:
            count = conn.execute('SELECT count(*) FROM mandala_engine.permits '
                                 'WHERE job_id = %s', (self.job_id,)).fetchone()[0]
        self.assertEqual(count, 0)

    def test_technical_qa_blocked_is_separate_from_render(self):
        import run_automatic_editing_v01 as workflow
        from test_automatic_editing_v01 import proposal

        self._free_until_director()
        candidate = proposal(workflow.read(self.output_root / str(self.job_id) / 'packet.json'))
        self.provider.replies['director'] = [json.dumps(candidate)]
        for expected in ('director', 'revision-controller', 'validator',
                         'revision-controller', 'renderer', 'revision-controller'):
            self.assertEqual(self.store.get_job(self.job_id)['next_action']['role'], expected)
            self.assertEqual(self.step()['state'], 'SUCCEEDED')
        with patch.object(workflow.core, 'verify_output',
                          side_effect=workflow.core.Error('TEST_ONLY forced QA failure')):
            task = self.step()
        self.assertEqual((task['state'], task['failure_class']),
                         ('BLOCKED', 'ACTUAL_MEDIA_QA_BLOCKED'))
        self.assertTrue((self.output_root / str(self.job_id) /
                         'proposal-01/render/preview.mp4').is_file())
        self.assertEqual(self.step()['state'], 'SUCCEEDED')  # Controller
        self.assertEqual(self.store.get_job(self.job_id)['next_action']['role'], 'director')

    def test_revision_loop_selects_best_private_preview_with_notes(self):
        import run_automatic_editing_v01 as workflow
        from test_automatic_editing_v01 import proposal

        self._free_until_director()
        root = self.output_root / str(self.job_id)
        candidate = proposal(workflow.read(root / 'packet.json'))
        self.provider.replies['director'] = [json.dumps(candidate)] * 3
        seen = []
        for _ in range(35):
            action = self.store.get_job(self.job_id)['next_action']
            if action is None:
                break
            role, attempt = action['role'], action['attempt']
            if role == 'reviewer':
                manifest = workflow.read(root / f'proposal-{attempt:02d}/render/manifest.json')
                issue = {'code': 'poor_framing', 'category': 'editorial',
                         'severity': 'minor' if attempt == 2 else 'major',
                         'start_sec': 0, 'end_sec': 1,
                         'diagnosis': 'Synthetic TEST_ONLY editorial framing note'}
                reply = {'media_sha256': manifest['output']['sha256'],
                         'video_examined': True, 'audio_examined': True,
                         'revision_required': True, 'issues': [issue],
                         'assessment': 'Synthetic TEST_ONLY output review; no real model observation.',
                         'human_verified': False, 'production_eligible': False}
                self.provider.replies['reviewer'] = [json.dumps({'text': json.dumps(reply)})]
            task = self.step()
            seen.append((role, attempt, task['state'], task['failure_class']))
            self.assertEqual(task['state'], 'SUCCEEDED', seen)
        else:
            self.fail('Revision loop exceeded bounded task count')
        job = self.store.get_job(self.job_id)
        self.assertEqual(job['state'], 'AUTO_PREVIEW_COMPLETED_WITH_NOTES')
        completed = workflow.read(root / 'completed.json')
        self.assertEqual((completed['selected_attempt'],
                          completed['director_proposals_reserved']), (2, 3))
        self.assertEqual(sum(r['kind'] == 'director' for r in
                             self.store.reservation_rows(self.job_id)), 3)
        self.assertEqual(sum(role == 'renderer' for role, _, _, _ in seen), 3)
        self.assertFalse(job['human_verified'])
        self.assertFalse(job['production_eligible'])
        self.assertFalse(job['publishing_eligible'])

    def test_crash_after_render_permit_consumption_never_retries(self):
        import renderer_revision_v02 as audio
        import run_automatic_editing_v01 as workflow
        from test_automatic_editing_v01 import proposal

        self._free_until_director()
        root = self.output_root / str(self.job_id)
        candidate = proposal(workflow.read(root / 'packet.json'))
        self.provider.replies['director'] = [json.dumps(candidate)]
        for expected in ('director', 'revision-controller', 'validator',
                         'revision-controller'):
            self.assertEqual(self.store.get_job(self.job_id)['next_action']['role'], expected)
            self.assertEqual(self.step()['state'], 'SUCCEEDED')
        with patch.object(audio.core, 'disk_preflight',
                          side_effect=RuntimeError('TEST_ONLY crash after admit')):
            task = self.step()
        self.assertEqual((task['state'], task['failure_class']),
                         ('RECONCILIATION_REQUIRED', 'EXECUTOR_UNCERTAIN'))
        self.assertTrue((root / 'proposal-01/permit-consumed.json').is_file())
        with psycopg.connect(self.dsn) as conn:
            permits = conn.execute('SELECT consumed_at FROM mandala_engine.permits '
                                   'WHERE job_id = %s', (self.job_id,)).fetchall()
        self.assertEqual(len(permits), 1)
        self.assertIsNotNone(permits[0][0])
        self.assertEqual(self.store.get_job(self.job_id)['state'],
                         'RECONCILIATION_REQUIRED')
        self.assertIsNone(self.dispatch.run_once())

    def test_synthetic_private_preview_role_chain(self):
        import run_automatic_editing_v01 as workflow
        from test_automatic_editing_v01 import proposal

        for expected in ('analyst', 'revision-controller', 'av-evidence',
                         'revision-controller', 'speech-asr', 'revision-controller'):
            self.assertEqual(self.store.get_job(self.job_id)['next_action']['role'], expected)
            self.assertEqual(self.step()['state'], 'SUCCEEDED')
        packet = workflow.read(self.output_root / str(self.job_id) / 'packet.json')
        candidate = proposal(packet)
        self.provider.replies['director'] = [json.dumps(candidate)]
        seen = []
        for _ in range(12):
            job = self.store.get_job(self.job_id)
            if not job['next_action']:
                break
            role = job['next_action']['role']
            if role == 'reviewer':
                manifest = workflow.read(self.output_root / str(self.job_id) /
                                         'proposal-01/render/manifest.json')
                self.provider.replies['reviewer'] = [json.dumps({'text': json.dumps({
                    'media_sha256': manifest['output']['sha256'],
                    'video_examined': True, 'audio_examined': True,
                    'revision_required': False, 'issues': [],
                    'assessment': 'Synthetic TEST_ONLY review response; no actual model observation.',
                    'human_verified': False, 'production_eligible': False})})]
            task = self.step()
            seen.append((role, task['state'], task['failure_class']))
            if task['state'] != 'SUCCEEDED':
                break
        self.assertEqual([r for r, _, _ in seen], [
            'director', 'revision-controller', 'validator', 'revision-controller',
            'renderer', 'revision-controller', 'technical-qa',
            'revision-controller', 'reviewer', 'revision-controller'], seen)
        self.assertIn(self.store.get_job(self.job_id)['state'],
                      ('AUTO_PREVIEW_COMPLETED', 'AUTO_PREVIEW_COMPLETED_WITH_NOTES'))
        root = self.output_root / str(self.job_id)
        with psycopg.connect(self.dsn) as conn:
            permits = conn.execute('''SELECT consumed_at FROM mandala_engine.permits
                WHERE job_id = %s''', (self.job_id,)).fetchall()
        self.assertEqual(len(permits), 1)
        self.assertIsNotNone(permits[0][0])
        self.assertTrue((root / 'proposal-01/permit-consumed.json').is_file())
        manifest = workflow.read(root / 'proposal-01/render/manifest.json')
        video = root / 'proposal-01/render/preview.mp4'
        self.assertEqual(hashlib.sha256(video.read_bytes()).hexdigest(),
                         manifest['output']['sha256'])
        self.assertEqual(video.stat().st_size, manifest['output']['bytes'])
        for row in self.store.artifact_rows(self.job_id):
            sha, size = self.store._file_reference(row['relative_path'])
            self.assertEqual((sha, size), (row['sha256'].strip(), row['byte_count']))
        import automatic_editing_validation_v01 as validator
        attempt = root / 'proposal-01'
        with self.assertRaisesRegex(ValueError, 'Output already exists'):
            validator.admit({'job': str(root), 'attempt': str(attempt)},
                workflow.read(attempt / 'visual-plan.json'),
                workflow.read(attempt / 'execution.json'), self.video,
                workflow.read(attempt / 'timeline.json'))

    def _speech_asr_source_review_retry(self):
        import run_automatic_editing_v01 as workflow

        for expected in ('analyst', 'revision-controller', 'av-evidence',
                         'revision-controller'):
            self.assertEqual(self.store.get_job(self.job_id)['next_action']['role'], expected)
            self.assertEqual(self.step()['state'], 'SUCCEEDED')
        self.assertEqual(self.store.get_job(self.job_id)['next_action']['role'], 'speech-asr')
        reply = {'status': 'complete', 'payload': {
            'text': 'one two three', 'words': [
                {'word': 'one', 'start': .3, 'end': .7},
                {'word': 'two', 'start': .8, 'end': 1.2},
                {'word': 'three', 'start': 1.3, 'end': 1.9}]}}
        self.provider.replies['asr'] = [reply, reply]
        self.assertEqual(self.step()['state'], 'SUCCEEDED')
        self.assertEqual(self.step()['state'], 'SUCCEEDED')  # Controller
        self.assertEqual(self.store.get_job(self.job_id)['next_action']['phase'], 'source_speech')
        issue = {'code': 'subtitle_uncertain', 'category': 'technical_evidence',
                 'severity': 'blocker', 'start_sec': .3, 'end_sec': 1.9,
                 'diagnosis': 'Synthetic TEST_ONLY first pass requests ASR retry'}
        first = {'media_sha256': self.sha, 'video_examined': True,
                 'audio_examined': True, 'revision_required': True,
                 'issues': [issue], 'assessment': 'Synthetic TEST_ONLY source review only.',
                 'human_verified': False, 'production_eligible': False}
        second = {**first, 'revision_required': False, 'issues': []}
        self.provider.replies['reviewer'] = [
            json.dumps({'text': json.dumps(first)}),
            json.dumps({'text': json.dumps(second)})]
        self.assertEqual(self.step()['state'], 'BLOCKED')
        self.assertEqual(self.step()['state'], 'SUCCEEDED')  # Controller
        action = self.store.get_job(self.job_id)['next_action']
        self.assertEqual((action['role'], action['regions']),
                         ('speech-asr', ['region-00']))
        self.assertEqual(self.step()['state'], 'SUCCEEDED')
        self.assertEqual(self.step()['state'], 'SUCCEEDED')  # Controller
        self.assertEqual(self.step()['state'], 'SUCCEEDED')  # Source Reviewer round 2
        self.assertEqual(self.step()['state'], 'SUCCEEDED')  # Controller
        self.assertEqual(self.store.get_job(self.job_id)['next_action']['role'], 'director')
        reservations = self.store.reservation_rows(self.job_id)
        self.assertEqual(sum(r['kind'] == 'speech_asr' for r in reservations), 2)
        self.assertEqual(sum(r['kind'] == 'reviewer_source' for r in reservations), 2)
        speech = workflow.read(self.output_root / str(self.job_id) / 'speech.json')
        self.assertEqual((speech['status'], speech['timing']),
                         ('AUTO_PREVIEW_ELIGIBLE', 'word'))

    def test_speech_asr_source_review_retry(self):
        self._speech_asr_source_review_retry()

    def test_speech_private_preview(self):
        import run_automatic_editing_v01 as workflow
        from test_automatic_editing_v01 import proposal, style

        self._speech_asr_source_review_retry()
        root = self.output_root / str(self.job_id)
        packet = workflow.read(root / 'packet.json')
        speech = workflow.read(root / 'speech.json')
        candidate = proposal(packet)
        candidate['audio'] = {'mode': 'original', 'start_sec': 0, 'gain_db': 0,
                              'fade_in_sec': 0, 'fade_out_sec': 0}
        candidate['overlays'] = []
        candidate['subtitle_groups'] = [{
            'id': 'spoken-words', 'shot_id': 's1',
            'unit_ids': [unit['id'] for unit in speech['units']], 'style': style()}]
        self.provider.replies['director'] = [json.dumps(candidate)]
        seen = []
        for _ in range(12):
            action = self.store.get_job(self.job_id)['next_action']
            if action is None:
                break
            if action['role'] == 'reviewer':
                manifest = workflow.read(root / 'proposal-01/render/manifest.json')
                reply = {'media_sha256': manifest['output']['sha256'],
                         'video_examined': True, 'audio_examined': True,
                         'revision_required': False, 'issues': [],
                         'assessment': 'Synthetic TEST_ONLY output review; no real model observation.',
                         'human_verified': False, 'production_eligible': False}
                self.provider.replies['reviewer'] = [json.dumps({'text': json.dumps(reply)})]
            task = self.step()
            seen.append((action['role'], task['state'], task['failure_class']))
            if task['state'] != 'SUCCEEDED':
                break
        self.assertEqual([role for role, _, _ in seen], [
            'director', 'revision-controller', 'validator', 'revision-controller',
            'renderer', 'revision-controller', 'technical-qa',
            'revision-controller', 'reviewer', 'revision-controller'], seen)
        self.assertIn(self.store.get_job(self.job_id)['state'],
                      ('AUTO_PREVIEW_COMPLETED', 'AUTO_PREVIEW_COMPLETED_WITH_NOTES'))


if __name__ == '__main__':
    unittest.main()
