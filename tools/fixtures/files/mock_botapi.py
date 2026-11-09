"""Deliberately unsafe mock upstream for the isolated gateway probe."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path

FILE_REQUESTS = 0

for name, path in [('STATE', '/private-state/binlog'), ('TEMP', '/private-temp/cache'),
                   ('SECRET', '/private-secret/token')]:
    Path(path).write_text('SYNTHETIC_' + name + '_MARKER')

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        global FILE_REQUESTS
        if self.path == '/stats':
            body, status = json.dumps({'file_requests': FILE_REQUESTS}).encode(), 200
        elif self.path.startswith('/bot'):
            body, status = b'SYNTHETIC_API_OK', 200
        elif self.path.startswith('/file'):
            FILE_REQUESTS += 1
            body, status = b'SYNTHETIC_STATE_MARKER', 200
        else:
            body, status = b'not found', 404
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

HTTPServer(('0.0.0.0', 8081), Handler).serve_forever()
