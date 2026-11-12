"""Synthetic, offline HTTP target. Never logs request paths or credentials."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

MARKER = 'SYNTHETIC_PRIVATE_MARKER_16'


class Handler(BaseHTTPRequestHandler):
    calls = []
    root_ok = True
    def do_GET(self):
        is_bot = self.path.startswith('/bot')
        # Spy records method classes only, never a token-bearing path.
        self.calls.append('getWebhookInfo' if is_bot else 'root' if self.path == '/' else 'other')
        if is_bot and self.path.endswith('/getWebhookInfo'):
            code, body = 200, dict(ok=True, result=dict(url='https://'+MARKER+'.invalid/', pending_update_count=0,
                            last_error_date=1, last_error_message='timeout '+MARKER))
        else:
            code, body = (404, dict(ok=False, error_code=404, description=MARKER)) if self.root_ok else (503, dict(error=MARKER))
        raw = json.dumps(body).encode()
        self.send_response(code); self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def log_message(self, *args): pass


class Stats(BaseHTTPRequestHandler):
    def do_GET(self):
        raw = (f'DURATION\tinf\t5sec\t1min\t1hour\nuptime\t1.0\nbot_count\t1\nactive_bot_count\t1\n\n'
               f'id\t1\nuptime\t1\ntoken\t123456:{MARKER}\nusername\t{MARKER}\nhead_update_id\t1\n'
               f'pending_update_count\t3\nwebhook\thttps://{MARKER}.invalid\n').encode()
        self.send_response(200); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def log_message(self, *args): pass


if __name__ == '__main__':
    threading.Thread(target=ThreadingHTTPServer(('127.0.0.1',8082),Stats).serve_forever,daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0',8081),Handler).serve_forever()
