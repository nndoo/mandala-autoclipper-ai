"""Read-only Stage 3 source admission through the existing Stage 6.3.2 gate."""

import re
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from backend.editing_store import Conflict, EditingStore, digest
from backend.media_worker.intake_adapter import IntakeError, prepare_intake


SOURCE_KEY = re.compile(r'tiktok:[0-9]{15,25}\Z')
SHA256 = re.compile(r'[0-9a-f]{64}\Z')
CONTRACT = 'stage6.3.5-v1'
SOURCE_QUERY = '''
    SELECT source_key, platform, username, video_id, status,
           original_local_path, original_size_bytes, original_sha256,
           original_duration_seconds, original_width, original_height
    FROM public.source_videos WHERE source_key = %s
'''


class SourceAdmission:
    def __init__(self, source_dsn, store: EditingStore, *, storage_root):
        self.source_dsn = source_dsn
        self.store = store
        self.storage_root = Path(storage_root)

    def admit(self, request, *, principal, key):
        """Admit only a matching ORIGINAL_READY row and original MP4.

        The source connection is read-only at both credential and transaction
        levels. Stage 5's intake adapter owns the media/hash/probe gate.
        """
        if (not isinstance(request, dict) or
                set(request) != {'contract_version', 'source_key', 'expected_sha256'} or
                request['contract_version'] != CONTRACT or
                not isinstance(request['source_key'], str) or
                not SOURCE_KEY.fullmatch(request['source_key']) or
                not isinstance(request['expected_sha256'], str) or
                not SHA256.fullmatch(request['expected_sha256'])):
            raise ValueError('Invalid admission contract')
        self.store._key(principal, key)
        fingerprint = digest(request)
        existing = self.store.lookup_key(principal, key, '/v1/jobs', fingerprint)
        if existing:
            return self.store.get_job(existing['job_id']), True

        with psycopg.connect(self.source_dsn, connect_timeout=5,
                             options='-c default_transaction_read_only=on',
                             row_factory=dict_row) as source:
            with source.cursor() as cur:
                cur.execute('SET TRANSACTION READ ONLY')
                cur.execute(SOURCE_QUERY, (request['source_key'],))
                record = cur.fetchone()
                if record is None:
                    raise IntakeError('Source is not ORIGINAL_READY')
                if record['original_sha256'] != request['expected_sha256']:
                    raise IntakeError('Source SHA-256 differs from admission request')
                intake = prepare_intake(record, storage_root=self.storage_root)
                # READ COMMITTED sees a new committed row on the second SELECT.
                # Execution must check again because filesystem/DB are not atomic.
                cur.execute(SOURCE_QUERY, (request['source_key'],))
                if cur.fetchone() != record:
                    raise Conflict('Source row changed during admission')

        return self.store.admit_verified(intake, principal=principal, key=key,
                                         request_sha256=fingerprint)

    def revalidate(self, job):
        """Recheck the admitted original immediately before a task effect."""
        with psycopg.connect(self.source_dsn, connect_timeout=5,
                             options='-c default_transaction_read_only=on',
                             row_factory=dict_row) as source:
            with source.cursor() as cur:
                cur.execute('SET TRANSACTION READ ONLY')
                cur.execute(SOURCE_QUERY, (job['source_key'],))
                record = cur.fetchone()
                if record is None:
                    raise IntakeError('Admitted source row is missing')
                intake = prepare_intake(record, storage_root=self.storage_root)
                cur.execute(SOURCE_QUERY, (job['source_key'],))
                if cur.fetchone() != record:
                    raise Conflict('Source row changed during revalidation')
        if (intake != job['source_snapshot'] or
                intake['metadata']['verification']['sha256'] != job['source_sha256'].strip()):
            raise Conflict('Admitted source identity changed')
        return intake
