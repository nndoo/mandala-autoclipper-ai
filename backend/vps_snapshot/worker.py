import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import psycopg

USERNAME = 'mandala.auto.kediri'
CHANNEL_ID = (
    'MS4wLjABAAAARRCOc1BxQyl9stiiH_Ow0X6508sdbl'
    'TUyU7zoTpuwDnuasR9zOUesydpwPbbBVOo'
)
ROOT = Path('/data/source')
ORIGINALS = ROOT / 'originals'
TEMP = ROOT / 'tmp'
LOCKS = ROOT / 'locks'
MAX_BYTES = 150 * 1024 * 1024
DOWNLOAD_GATE = threading.BoundedSemaphore(value=1)


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def verify_claim(video_id, claim_token, *, for_update=False):
    required = ('PGHOST', 'PGUSER', 'PGPASSWORD')
    if any(not os.getenv(key) for key in required):
        raise ApiError(503, 'PostgreSQL worker configuration is missing')
    try:
        connection = psycopg.connect(
            host=os.environ['PGHOST'],
            port=int(os.getenv('PGPORT', '5432')),
            dbname=os.getenv('PGDATABASE', 'mandala_autoclipper'),
            user=os.environ['PGUSER'],
            password=os.environ['PGPASSWORD'],
            connect_timeout=5,
        )
    except (psycopg.Error, ValueError) as exc:
        print('DB connection error:', type(exc).__name__, flush=True)
        raise ApiError(503, 'Reservation database unavailable') from exc

    # The caller owns the connection; a transaction is needed for final promotion.
    try:
        with connection.cursor() as cur:
            query = '''
                SELECT source_key
                FROM public.source_videos
                WHERE source_key = %s
                  AND platform = 'tiktok'
                  AND username = %s
                  AND video_id = %s
                  AND status = 'RESERVED'
                  AND claim_token = %s::uuid
                  AND lease_expires_at > NOW()
            ''' + (' FOR UPDATE' if for_update else '')
            cur.execute(query, (f'tiktok:{video_id}', USERNAME, video_id, claim_token))
            valid = cur.fetchone() is not None
        if not valid:
            connection.rollback()
            connection.close()
            raise ApiError(409, 'Reservation is missing, expired or owned by another claim')
        return connection
    except ApiError:
        raise
    except psycopg.Error as exc:
        connection.rollback()
        connection.close()
        print('DB query error:', type(exc).__name__, flush=True)
        raise ApiError(503, 'Reservation lookup failed') from exc


def verify_original_access(video_id, claim_token, expected_path):
    """Authorize a read of an already validated MP4 using an active reservation."""
    required = ('PGHOST', 'PGUSER', 'PGPASSWORD')
    if any(not os.getenv(key) for key in required):
        raise ApiError(503, 'PostgreSQL worker configuration is missing')
    try:
        with psycopg.connect(
            host=os.environ['PGHOST'],
            port=int(os.getenv('PGPORT', '5432')),
            dbname=os.getenv('PGDATABASE', 'mandala_autoclipper'),
            user=os.environ['PGUSER'],
            password=os.environ['PGPASSWORD'],
            connect_timeout=5,
            options='-c default_transaction_read_only=on',
        ) as connection:
            with connection.cursor() as cur:
                cur.execute('''
                    SELECT original_local_path, original_size_bytes, original_sha256
                    FROM public.source_videos
                    WHERE source_key = %s
                      AND platform = 'tiktok'
                      AND username = %s
                      AND video_id = %s
                      AND status = 'ORIGINAL_READY'
                      AND claim_token = %s::uuid
                      AND lease_expires_at > NOW()
                ''', (f'tiktok:{video_id}', USERNAME, video_id, claim_token))
                row = cur.fetchone()
    except (psycopg.Error, ValueError) as exc:
        print('Original lookup error:', type(exc).__name__, flush=True)
        raise ApiError(503, 'Original metadata lookup failed') from exc
    if not row:
        raise ApiError(409, 'Original is not ready, or reservation is missing/expired')
    original_path, db_size, db_sha = row
    if original_path != str(expected_path) or not db_sha or not db_size:
        raise ApiError(409, 'Original metadata incomplete or path mismatch')
    return int(db_size), str(db_sha)


def probe_and_decode(path):
    try:
        meta_result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
            capture_output=True, text=True, timeout=25,
        )
        if meta_result.returncode != 0:
            raise ApiError(422, 'FFprobe rejected downloaded media')
        meta = json.loads(meta_result.stdout)
        streams = meta.get('streams', [])
        v = next((s for s in streams if s.get('codec_type') == 'video'), None)
        audio_present = any(s.get('codec_type') == 'audio' for s in streams)
        duration = float(meta.get('format', {}).get('duration', '0'))
        width = int(v.get('width', 0)) if v else 0
        height = int(v.get('height', 0)) if v else 0
        if not (1 <= duration <= 1200 and width >= 320 and height >= 320):
            raise ApiError(422, 'Media duration or dimensions are outside limits')

        decode = subprocess.run(
            ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-xerror', '-i', str(path),
             '-map', '0:v:0', '-map', '0:a?', '-f', 'null', '-'],
            capture_output=True, text=True, timeout=180,
        )
        if decode.returncode != 0:
            raise ApiError(422, 'FFmpeg full-decode validation failed')
        return {
            'durationSeconds': duration,
            'width': width,
            'height': height,
            'videoCodec': v.get('codec_name', '') if v else '',
            'audioPresent': audio_present,
        }
    except subprocess.TimeoutExpired as exc:
        raise ApiError(504, 'Media validation timed out') from exc
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ApiError(422, 'Invalid media metadata') from exc


def describe_media(path):
    size = path.stat().st_size
    if not 1024 <= size <= MAX_BYTES:
        raise ApiError(422, 'File size outside allowed bounds')
    media = probe_and_decode(path)
    checksum = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            checksum.update(chunk)
    return {'sizeBytes': size, 'sha256': checksum.hexdigest(), **media}


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_payload(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 1 <= size <= 4096:
                raise ApiError(400, 'Invalid body size')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ApiError(400, 'Expected JSON object')
            return data
        except (ValueError, json.JSONDecodeError) as exc:
            raise ApiError(400, 'Malformed request body') from exc

    def do_GET(self):
        if self.path == '/health':
            return self.respond(200, {'status': 'ok', 'service': 'autoclipper-media-worker'})
        return self.respond(404, {'error': 'Not found'})

    def do_POST(self):
        if self.path == '/source/download':
            return self.download_original()
        if self.path == '/source/file':
            return self.serve_original_file()
        if self.path != '/source/discover':
            return self.respond(404, {'error': 'Not found'})
        try:
            payload = self.read_payload()
            username = payload.get('username')
            limit = int(payload.get('maxVideos', 10))
            if username != USERNAME:
                raise ApiError(400, 'Invalid username')
            if not 1 <= limit <= 10:
                raise ApiError(400, 'Invalid limit')
            result = subprocess.run(
                ['yt-dlp', '--impersonate', 'chrome', '--flat-playlist',
                 '--playlist-end', str(limit), '--skip-download',
                 '--socket-timeout', '15', '--retries', '1',
                 '--extractor-retries', '1', '--dump-single-json',
                 f'tiktokuser:{CHANNEL_ID}'],
                capture_output=True, text=True, timeout=95,
            )
            if result.returncode != 0:
                raise ApiError(502, 'Discovery failed')
            data = json.loads(result.stdout)
            videos = []
            for item in data.get('entries', []):
                video_id = str(item.get('id') or '')
                if not video_id.isdigit():
                    continue
                videos.append({
                    'videoId': video_id,
                    'url': f'https://www.tiktok.com/@{USERNAME}/video/{video_id}',
                    'title': item.get('title') or '',
                })
            if not videos:
                raise ApiError(502, 'No videos discovered')
            return self.respond(200, {
                'success': True, 'username': USERNAME,
                'count': len(videos), 'videos': videos,
            })
        except subprocess.TimeoutExpired:
            return self.respond(504, {'error': 'Discovery timeout'})
        except ApiError as exc:
            return self.respond(exc.status, {'error': exc.message})
        except Exception as exc:
            print('Discovery unexpected error:', type(exc).__name__, flush=True)
            return self.respond(502, {'error': 'Discovery failed'})

    def serve_original_file(self):
        """Stream the exact validated MP4 for n8n's Binary File response."""
        try:
            payload = self.read_payload()
            video_id = str(payload.get('videoId') or '')
            raw_token = str(payload.get('claimToken') or '')
            if not re.fullmatch(r'\d{15,25}', video_id):
                raise ApiError(400, 'Invalid videoId')
            try:
                claim_token = str(uuid.UUID(raw_token))
            except ValueError as exc:
                raise ApiError(400, 'Invalid claimToken') from exc

            path = ORIGINALS / f'{video_id}.mp4'
            db_size, db_sha = verify_original_access(video_id, claim_token, path)

            # An active claim alone is insufficient: verify bytes against the DB.
            try:
                with path.open('rb') as fp:
                    actual_size = os.fstat(fp.fileno()).st_size
                    if not (1024 <= actual_size <= MAX_BYTES) or actual_size != db_size:
                        raise ApiError(409, 'Original file size differs from database')
                    sha = hashlib.sha256()
                    while True:
                        chunk = fp.read(1024 * 1024)
                        if not chunk:
                            break
                        sha.update(chunk)
                    if sha.hexdigest() != db_sha:
                        raise ApiError(409, 'Original checksum differs from database')

                    fp.seek(0)
                    self.send_response(200)
                    self.send_header('Content-Type', 'video/mp4')
                    self.send_header('Content-Disposition', f'attachment; filename="{video_id}.mp4"')
                    self.send_header('Content-Length', str(actual_size))
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.end_headers()
                    while True:
                        chunk = fp.read(1024 * 1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except FileNotFoundError as exc:
                raise ApiError(404, 'Original file not found') from exc
        except ApiError as exc:
            return self.respond(exc.status, {'success': False, 'error': exc.message})
        except (BrokenPipeError, ConnectionResetError):
            print('Original file stream interrupted by client', flush=True)
        except OSError as exc:
            print('Original file error:', type(exc).__name__, flush=True)
            # If headers already went out, sending JSON is unsafe. Keep connection closed.
            self.close_connection = True

    def download_original(self):
        temp_dir = None
        lock_handle = None
        gate_acquired = False
        try:
            payload = self.read_payload()
            video_id = str(payload.get('videoId') or '')
            raw_claim_token = str(payload.get('claimToken') or '')
            if not re.fullmatch(r'\d{15,25}', video_id):
                raise ApiError(400, 'Invalid videoId')
            try:
                claim_token = str(uuid.UUID(raw_claim_token))
            except ValueError as exc:
                raise ApiError(400, 'Invalid claimToken') from exc

            # Validate against the actual PostgreSQL reservation before any work.
            with verify_claim(video_id, claim_token) as conn:
                conn.rollback()

            if not DOWNLOAD_GATE.acquire(blocking=False):
                raise ApiError(429, 'Another media download is in progress')
            gate_acquired = True

            for folder in (ORIGINALS, TEMP, LOCKS):
                folder.mkdir(parents=True, exist_ok=True)
            lock_handle = (LOCKS / f'{video_id}.lock').open('a+b')
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ApiError(409, 'Video download is already in progress') from exc

            final_path = ORIGINALS / f'{video_id}.mp4'
            if final_path.is_file():
                try:
                    existing = describe_media(final_path)
                    return self.respond(200, {
                        'success': True, 'alreadyExists': True,
                        'videoId': video_id, 'sourceKey': f'tiktok:{video_id}',
                        'claimToken': claim_token,
                        'localPath': str(final_path), **existing,
                    })
                except ApiError:
                    # Never overwrite/delete an unexpected existing file.
                    raise ApiError(409, 'Existing original requires manual inspection')

            temp_dir = Path(tempfile.mkdtemp(prefix=f'{video_id}-', dir=TEMP))
            output_pattern = str(temp_dir / f'{video_id}.%(ext)s')
            url = f'https://www.tiktok.com/@{USERNAME}/video/{video_id}'
            command = [
                'yt-dlp', '--impersonate', 'chrome', '--no-playlist',
                '--format', 'best[ext=mp4]', '--max-filesize', '150M',
                '--socket-timeout', '15', '--retries', '1',
                '--fragment-retries', '1', '--no-mtime',
                '-o', output_pattern, url,
            ]
            download = subprocess.run(command, capture_output=True, text=True, timeout=180)
            if download.returncode != 0:
                print('yt-dlp download error:', download.stderr[-600:], flush=True)
                raise ApiError(502, 'TikTok video download failed')

            candidate = temp_dir / f'{video_id}.mp4'
            if not candidate.is_file():
                raise ApiError(502, 'yt-dlp did not produce expected MP4')
            result = describe_media(candidate)

            # Recheck ownership while holding a DB row lock, then promote atomically.
            conn = verify_claim(video_id, claim_token, for_update=True)
            try:
                if final_path.exists():
                    raise ApiError(409, 'Original was created by another request')
                os.replace(candidate, final_path)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

            return self.respond(200, {
                'success': True, 'alreadyExists': False,
                'videoId': video_id, 'sourceKey': f'tiktok:{video_id}',
                'claimToken': claim_token, 'localPath': str(final_path),
                **result,
            })
        except ApiError as exc:
            return self.respond(exc.status, {'success': False, 'error': exc.message})
        except subprocess.TimeoutExpired:
            return self.respond(504, {'success': False, 'error': 'Download timed out'})
        except (OSError, psycopg.Error) as exc:
            print('Download system error:', type(exc).__name__, flush=True)
            return self.respond(500, {'success': False, 'error': 'Download system error'})
        except Exception as exc:
            print('Download unexpected error:', type(exc).__name__, flush=True)
            return self.respond(500, {'success': False, 'error': 'Download unexpected error'})
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)
            if lock_handle is not None:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
                lock_handle.close()
            if gate_acquired:
                DOWNLOAD_GATE.release()


if __name__ == '__main__':
    print('Media Worker API listening on port 3002', flush=True)
    ThreadingHTTPServer(('0.0.0.0', 3002), Handler).serve_forever()
