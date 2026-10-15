"""Editing worker process on internal port 3003."""

import os
import threading
from http.server import ThreadingHTTPServer

from backend.editing_api import EditingService, Handler
from backend.editing_dispatch import Dispatcher


def create_server(service, *, host='127.0.0.1', port=0, start_dispatcher=False):
    server = ThreadingHTTPServer((host, port), Handler)
    server.service = service
    if start_dispatcher and service.executor is not None:
        dispatcher = Dispatcher(service.store, service.admission,
                                executor=service.executor, ready=service.ready)
        thread = threading.Thread(target=dispatcher.run, daemon=True)
        thread.start()
        server.dispatcher = dispatcher
        server.dispatch_thread = thread
    return server


def main():
    port = int(os.getenv('MANDALA_EDITING_PORT', '3003'))
    if port != 3003:
        raise SystemExit('Editing worker must listen on port 3003')
    server = create_server(EditingService.from_env(), host='0.0.0.0', port=port,
                           start_dispatcher=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
