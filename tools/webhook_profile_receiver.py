"""Loopback-only receipt receiver. Manual POST is receiver evidence, not Bot API delivery."""
import argparse
import hmac
import json
import os
from pathlib import Path
import re
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def expected_secret(environ=None):
    env = os.environ if environ is None else environ
    present = [key for key in ("WEBHOOK_SECRET_TOKEN", "WEBHOOK_SECRET_TOKEN_FILE") if key in env]
    if len(present) != 1:
        raise ValueError("Exactly one protected expected-secret input is required")
    if present[0].endswith("_FILE"):
        path = Path(env[present[0]]).resolve()
        if Path(__file__).resolve().parents[1] in path.parents:
            raise ValueError("Expected-secret file must be outside checkout/webroot")
        raw = path.read_bytes()
        if len(raw) > 258:
            raise ValueError("Invalid expected-secret file")
        if raw.endswith(b"\r\n"):
            raw = raw[:-2]
        elif raw.endswith(b"\n"):
            raw = raw[:-1]
        value = raw.decode("ascii")
    else:
        value = env[present[0]]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value, flags=re.ASCII):
        raise ValueError("Invalid expected secret")
    return value.encode("ascii")


class Receiver(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, secret, expected_update_id=None):
        self.secret = secret
        self.expected_update_id = expected_update_id
        self.receipts = []
        import threading
        self.receipt_lock = threading.Lock()
        super().__init__(("127.0.0.1", 0), Handler)

    def handle_error(self, request, client_address):
        pass  # Never dump HTTP parsing errors containing private input.


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(3)

    def log_message(self, *args):
        pass

    def reply(self, status, receipt=None):
        body = json.dumps(receipt or {"accepted": False}).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        values = self.headers.get_all("X-Telegram-Bot-Api-Secret-Token", [])
        if len(values) != 1 or not hmac.compare_digest(values[0].encode("utf-8"), self.server.secret):
            self.reply(403)
            return
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isdigit():
            self.reply(400)
            return
        length = int(lengths[0])
        if not 0 < length <= 65536:
            self.reply(413)
            return
        deadline, data = time.monotonic() + 3, bytearray()
        try:
            while len(data) < length:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                self.connection.settimeout(remaining)
                chunk = self.rfile.read1(min(4096, length - len(data)))
                if not chunk:
                    raise ValueError
                data.extend(chunk)
            update = json.loads(data)
            update_id = update.get("update_id") if isinstance(update, dict) else None
            if type(update_id) is not int or update_id < 0:
                raise ValueError
        except (ValueError, UnicodeError, TimeoutError, socket.timeout):
            self.reply(400)
            return
        if self.server.expected_update_id is not None and update_id != self.server.expected_update_id:
            self.reply(409)
            return
        with self.server.receipt_lock:
            receipt = {"update_id": update_id, "time": time.time(), "secret_matched": True,
                       "count": len(self.server.receipts) + 1}
            self.server.receipts.append(receipt)
        self.reply(200, receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-update-id", type=int)
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error("seconds must be 1..3600")
    try:
        secret = expected_secret()
    except (ValueError, OSError, UnicodeError):
        parser.exit(2, "Protected expected-secret input unavailable or invalid\n")
    with Receiver(secret, args.expected_update_id) as server:
        print(json.dumps({"loopback_port": server.server_port}), flush=True)
        server.timeout = 0.2
        deadline = time.monotonic() + args.seconds
        try:
            while time.monotonic() < deadline:
                server.handle_request()
        except KeyboardInterrupt:
            pass
        for receipt in server.receipts:
            print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
