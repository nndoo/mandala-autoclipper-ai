"""Editing runtime canary entrypoint; role/job routes are not implemented yet."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from backend.runtime_check import inspect


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/health':
            self.respond(200, {'status': 'ok', 'service': 'mandala-ai-editing-worker',
                               'phase': 'runtime-preparation', 'roles_ready': False})
        else:
            self.respond(404, {'error': 'Endpoint not implemented'})

    def do_POST(self):
        self.respond(404, {'error': 'Endpoint not implemented'})


def main():
    result = inspect(check_storage=True, require_service_env=True)
    print(json.dumps(result), flush=True)
    if result['status'] != 'PASS':
        raise SystemExit(1)
    port = int(os.getenv('MANDALA_EDITING_PORT', '3003'))
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()


if __name__ == '__main__':
    main()
