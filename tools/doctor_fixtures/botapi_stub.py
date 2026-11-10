#!/usr/local/bin/python3
"""Synthetic plumbing only. No Telegram connection, authorization or bot methods."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if __name__ == "__main__":
    if "--version" in sys.argv:
        print("Bot API 0.0.0 (synthetic doctor fixture)")
        sys.exit(0)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            with open("/audit/requests.log", "a", encoding="utf-8") as stream:
                stream.write(json.dumps(self.path) + "\n")
            payload = json.dumps({"ok": False, "error_code": 404}).encode()
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    class Stats(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = b'DURATION\tinf\t5sec\t1min\t1hour\nuptime\t1.0\nbot_count\t0\nactive_bot_count\t0\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers(); self.wfile.write(payload)
        def log_message(self, *args): pass

    import os
    if os.getenv('TELEGRAM_STAT', 'false') == 'true':
        threading.Thread(target=ThreadingHTTPServer(('127.0.0.1', 8082), Stats).serve_forever, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8081), Handler).serve_forever()
