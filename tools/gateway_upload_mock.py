"""Streaming synthetic upstream. Never use with real tokens or expose publicly."""
import argparse
import hashlib
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHUNK = 65536


class Multipart:
    """Bounded-memory multipart parser, including delimiters split across reads."""
    def __init__(self, boundary):
        self.marker = b"\r\n--" + boundary
        self.pending = b""
        self.state = "first"
        self.parts = []
        self.current = None
        self.digest = hashlib.sha256()
        self.size = 0

    def feed(self, data):
        self.digest.update(data)
        self.size += len(data)
        self.pending += data
        while True:
            if self.state == "done":
                if len(self.pending) > 2:
                    raise ValueError("data after final boundary")
                return
            if self.state == "first":
                first = self.marker[2:] + b"\r\n"
                if len(self.pending) < len(first):
                    return
                if not self.pending.startswith(first):
                    raise ValueError("invalid first boundary")
                self.pending = self.pending[len(first):]
                self.state = "headers"
            elif self.state == "headers":
                end = self.pending.find(b"\r\n\r\n")
                if end < 0:
                    if len(self.pending) > 8192:
                        raise ValueError("oversized part headers")
                    return
                header = self.pending[:end].decode("ascii")
                if end > 8192 or len(self.parts) >= 64:
                    raise ValueError("multipart metadata limit")
                self.current = {"headers": header, "bytes": 0, "hash": hashlib.sha256()}
                self.pending = self.pending[end + 4:]
                self.state = "body"
            elif self.state == "body":
                end = self.pending.find(self.marker)
                if end < 0:
                    count = max(0, len(self.pending) - len(self.marker) - 2)
                    self.consume(self.pending[:count])
                    self.pending = self.pending[count:]
                    return
                if len(self.pending) < end + len(self.marker) + 2:
                    return
                suffix = self.pending[end + len(self.marker):end + len(self.marker) + 2]
                if suffix not in (b"--", b"\r\n"):
                    self.consume(self.pending[:end + 2])
                    self.pending = self.pending[end + 2:]
                    continue
                self.consume(self.pending[:end])
                part = self.current
                part["sha256"] = part.pop("hash").hexdigest()
                self.parts.append(part)
                self.pending = self.pending[end + len(self.marker) + 2:]
                self.state = "done" if suffix == b"--" else "headers"

    def consume(self, data):
        self.current["bytes"] += len(data)
        self.current["hash"].update(data)

    def finish(self):
        if self.state != "done" or self.pending not in (b"", b"\r\n"):
            raise ValueError("incomplete multipart")
        return {"body_bytes": self.size, "body_sha256": self.digest.hexdigest(), "parts": self.parts}


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.receipts = {}
        self.controls = {}

    def update(self, case, **values):
        with self.lock:
            self.receipts.setdefault(case, {}).update(values)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def reply(self, value, status=200):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/__receipts":
            with self.server.state.lock:
                data = json.loads(json.dumps(self.server.state.receipts))
            self.reply(data)
        else:
            self.reply({"uri": self.path})

    def do_POST(self):
        state = self.server.state
        if self.path == "/__control":
            size = int(self.headers.get("Content-Length", "0"))
            if size > 8192:
                self.reply({}, 400)
                return
            data = json.loads(self.rfile.read(size))
            with state.lock:
                state.controls[data["case"]] = data
            self.reply({"ok": True})
            return
        case = self.headers.get("X-Case", "anonymous")
        self.connection.settimeout(1200)
        control = state.controls.get(case, {})
        if control.get("read_pause"):
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16384)
        state.update(case, started=time.monotonic(), uri=self.path, received=0)
        content_type = self.headers.get("Content-Type", "")
        parser = Multipart(content_type.split("boundary=", 1)[1].encode()) if "boundary=" in content_type else None
        digest, count = hashlib.sha256(), 0
        try:
            remaining = int(self.headers.get("Content-Length", "0"))
            chunked = self.headers.get("Transfer-Encoding", "").lower() == "chunked"
            while remaining or chunked:
                if chunked:
                    line = self.rfile.readline(128)
                    if not line:
                        raise EOFError("missing chunk")
                    remaining = int(line.split(b";", 1)[0], 16)
                    if remaining == 0:
                        if self.rfile.read(2) != b"\r\n":
                            raise ValueError("invalid final chunk")
                        break
                while remaining:
                    data = self.rfile.read(min(CHUNK, remaining))
                    if not data:
                        raise EOFError("short body")
                    if not count:
                        state.update(case, first_byte=time.monotonic())
                        delay = float(control.get("read_pause", 0))
                        if delay:
                            state.update(case, stall_started=time.monotonic())
                            time.sleep(delay)
                            state.update(case, resumed=time.monotonic())
                    count += len(data)
                    remaining -= len(data)
                    digest.update(data)
                    if parser:
                        parser.feed(data)
                    state.update(case, received=count, progress=time.monotonic())
                if chunked and self.rfile.read(2) != b"\r\n":
                    raise ValueError("invalid chunk delimiter")
            result = parser.finish() if parser else {"body_bytes": count, "body_sha256": digest.hexdigest(), "parts": []}
            state.update(case, **result, body_received=time.monotonic())
            time.sleep(float(control.get("response_pause", 0)))
            self.reply(result, status=int(control.get("status", 200)))
            state.update(case, response_sent=time.monotonic())
        except (ValueError, EOFError, OSError) as exc:
            state.update(case, aborted=time.monotonic(), error=type(exc).__name__)
            self.close_connection = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    server.daemon_threads = True
    server.state = State()
    server.serve_forever()


if __name__ == "__main__":
    main()
