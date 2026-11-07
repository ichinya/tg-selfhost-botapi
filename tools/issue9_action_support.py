"""Stateful stdlib-only loopback Bot API. Synthetic state is never sent elsewhere."""
from contextlib import contextmanager
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs


class State:
    def __init__(self, source='', target='', fault=None):
        self.hooks = dict(source=source, target=target)
        self.profiles = {role: dict(allowed_updates=[], max_connections=40, has_custom_certificate=False)
                         for role in ('source', 'target')}
        self.queues = dict(source=3, target=5)
        self.calls = []
        self.fault = fault


@contextmanager
def mock_api(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.handle_api()

        def do_POST(self):
            self.handle_api()

        def handle_api(self):
            role = self.path.split('/')[1]
            if role not in state.hooks:
                self.send_error(404)
                return
            method = self.path.rsplit('/', 1)[-1] if '/bot' in self.path else 'probe'
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            content_type = self.headers.get('Content-Type', '')
            if content_type.startswith('multipart/form-data'):
                msg = BytesParser(policy=default).parsebytes(
                    ('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + body)
                data = {part.get_param('name', header='content-disposition'):
                        part.get_payload(decode=True).decode() for part in msg.iter_parts()}
            else:
                data = {key: values[0] for key, values in parse_qs(body.decode(), keep_blank_values=True).items()}
            state.calls.append(dict(role=role, method=method, data=data))
            fault = state.fault if role == 'target' and method in ('deleteWebhook', 'setWebhook', 'getWebhookInfo') else None
            if method == 'probe':
                self.reply(dict(ok=False, error_code=404, description='Not Found'), 404)
                return
            mutation = method in ('deleteWebhook', 'setWebhook')
            if mutation and fault in ('http', 'api', 'false-result', 'malformed', 'lost-before'):
                if fault == 'lost-before':
                    self.connection.close()
                elif fault == 'malformed':
                    self.reply_raw(b'{')
                else:
                    self.reply(dict(ok=fault != 'api', result=False), 500 if fault == 'http' else 200)
                return
            if method == 'getMe':
                result = dict(id=123)
            elif method == 'getWebhookInfo':
                result = dict(url=state.hooks[role], **state.profiles[role])
                if fault == 'null-url': result['url'] = None
                if fault == 'missing-url': del result['url']
                if fault == 'number-url': result['url'] = 12
                if fault == 'wrong-url': result['url'] = 'https://wrong.example/'
                if fault == 'profile-mismatch': result['max_connections'] = 77
            else:
                result = True
                if method == 'deleteWebhook': state.hooks[role] = ''
                if method == 'setWebhook':
                    state.hooks[role] = data['url']
                    state.profiles[role] = dict(allowed_updates=json.loads(data['allowed_updates']),
                        max_connections=int(data['max_connections']), has_custom_certificate='certificate' in data)
                    if 'ip_address' in data: state.profiles[role]['ip_address'] = data['ip_address']
                if mutation and data.get('drop_pending_updates') == 'true': state.queues[role] = 0
                if mutation and fault == 'lost-after':
                    self.connection.close()
                    return
            self.reply(dict(ok=True, result=result))

        def reply(self, value, status=200):
            self.reply_raw(json.dumps(value).encode(), status)

        def reply_raw(self, value, status=200):
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(value)))
            self.end_headers()
            self.wfile.write(value)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
