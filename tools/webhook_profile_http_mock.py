"""Loopback Bot API test peer; actual urlencoded/multipart parser. No external traffic."""
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import threading
from urllib.parse import parse_qs


class MockAPI(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, failure=None, readback=None, receiver_port=None):
        self.calls, self.failure, self.readback = [], failure, readback or {}
        self.receiver_port = receiver_port
        self.applied = False
        self.source = {"url": "https://sink.test/webhook", "max_connections": 40,
                       "has_custom_certificate": False, "pending_update_count": 0}
        self.target = {**self.source, "url": ""}
        super().__init__(("127.0.0.1", 0), MockHandler)

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server_port}"

    def start(self):
        thread = threading.Thread(target=self.serve_forever, daemon=True)
        thread.start()
        return thread


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.do_GET()

    def do_GET(self):
        role = self.path.split("/")[1]
        method = self.path.rsplit("/", 1)[-1] if "/bot" in self.path else "probe"
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        fields, files = {}, {}
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            message = BytesParser(policy=policy.default).parsebytes(b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body)
            for part in message.iter_parts():
                key = part.get_param("name", header="content-disposition")
                value = part.get_payload(decode=True)
                if part.get_filename():
                    files[key] = value
                else:
                    fields[key] = value.decode()
        else:
            fields = {k: v[0] for k, v in parse_qs(body.decode(), keep_blank_values=True).items()}
        self.server.calls.append({"role": role, "method": method, "fields": fields, "files": files})
        if method == "probe":
            self.reply(404, {"ok": False, "error_code": 404, "description": "Not Found"})
            return
        state = self.server.source if role == "source" else self.server.target
        if method == "getMe":
            result = {"id": 123, "first_name": "Synthetic"}
        elif method == "getWebhookInfo":
            result = {**state, **(self.server.readback if self.server.applied else {})}
        else:
            result = True
        failure = self.server.failure
        failed = failure and failure[0] == f"{role}:{method}"
        if not failed or failure[1] == "lost":
            if method == "deleteWebhook":
                state["url"] = ""
            if method == "setWebhook":
                state.update(url=fields["url"], allowed_updates=json.loads(fields["allowed_updates"]),
                             max_connections=int(fields["max_connections"]), has_custom_certificate="certificate" in files)
                if "ip_address" in fields:
                    state["ip_address"] = fields["ip_address"]
                self.server.applied = True
                if self.server.receiver_port:
                    conn = http.client.HTTPConnection("127.0.0.1", self.server.receiver_port, timeout=5)
                    conn.request("POST", "/", b'{"update_id":701}', {"X-Telegram-Bot-Api-Secret-Token": fields.get("secret_token", "")})
                    response = conn.getresponse()
                    response.read()
                    conn.close()
        if failed:
            kind = failure[1]
            if kind == "lost":
                self.connection.close()
                return
            if kind == "http":
                self.reply(500, {"ok": False, "description": "Synthetic_secret_7 reflected"})
                return
            if kind == "malformed":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{Synthetic_secret_7")
                return
            if kind == "false-result":
                result = False
            else:
                self.reply(200, {"ok": False, "error_code": 429, "description": "Synthetic_secret_7 reflected"})
                return
        self.reply(200, {"ok": True, "result": result})

    def reply(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
