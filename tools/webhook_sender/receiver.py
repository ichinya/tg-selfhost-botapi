"""Loopback receiver for the production sender component, including its ACK."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess
import threading
import uuid


def valid_delivery(method, path, headers, body, nonce, expected):
    try:
        payload = json.loads(body)
        return (method == "POST" and path == "/probe"
                and headers.get_all("User-Agent") == [expected]
                and payload["message"]["text"] == nonce
                and isinstance(payload["update_id"], int))
    except (ValueError, KeyError, TypeError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", default="WebhookDelivery/1.0")
    args = parser.parse_args()
    nonce, accepted = uuid.uuid4().hex, []

    class Receiver(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(2)

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(size) if 0 < size < 65536 else b""
            good = valid_delivery(self.command, self.path, self.headers, body, nonce, args.expected)
            if good:
                accepted.append(True)
            response = b'{"ok":true}' if good else b'{"ok":false}'
            self.send_response(200 if good else 403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Receiver) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(["/usr/local/libexec/webhook-sender", str(server.server_port), nonce],
                                    capture_output=True, text=True, timeout=15)
            if result.returncode or not accepted or json.loads(result.stdout) != {"queue_acknowledged": True}:
                return 1
            print(json.dumps({"status": "PASS", "post": True, "user_agent": args.expected, "queue_acknowledged": True}))
            return 0
        finally:
            server.shutdown()
            thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
