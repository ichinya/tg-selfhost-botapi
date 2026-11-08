#!/usr/local/bin/python3
"""Synthetic plumbing only. No Telegram connection, authorization or bot methods."""
import json
import sys
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

    ThreadingHTTPServer(("0.0.0.0", 8081), Handler).serve_forever()
