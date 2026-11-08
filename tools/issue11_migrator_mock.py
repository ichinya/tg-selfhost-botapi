"""Loopback-only fixtures for the public Bash migrator; no production imports."""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = '12345:SYNTHETIC_TOKEN'
WEBHOOK = 'https://example.invalid/private-hook'
METHODS = ('getMe', 'getWebhookInfo', 'deleteWebhook', 'logOut', 'setWebhook')
MUTATIONS = ('deleteWebhook', 'logOut', 'setWebhook')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def handle_request(self):
        state, role = self.server.state, self.server.role
        method = self.path.rsplit('/', 1)[-1]
        if self.path != '/bot' + TOKEN + '/' + method or method not in METHODS:
            self.send_error(400)
            return
        if self.headers.get('Content-Length'):
            self.rfile.read(int(self.headers['Content-Length']))
        state.calls.append((role, method))
        targeted = ((role, method) == state.target and
                    state.calls.count((role, method)) == state.occurrence)
        scenario = state.scenario if targeted else 'success'
        if targeted:
            state.entered.set()
        if scenario in ('lost', 'lost_no_effect', 'partial', 'delayed', 'slow', 'barrier'):
            if scenario != 'lost_no_effect':
                state.effects.append((role, method))
            if scenario == 'barrier':
                state.release.wait(8)
            elif scenario == 'delayed':
                state.release.wait(2)
            elif scenario in ('partial', 'slow'):
                self.send_response(200)
                self.send_header('Content-Length', '10000')
                self.end_headers()
                try:
                    self.wfile.write(b'{"ok":true,"result":true}')
                    self.wfile.flush()
                    if scenario == 'partial':
                        self.close_connection = True
                        return
                    for _ in range(25):
                        self.wfile.write(b' ')
                        self.wfile.flush()
                        if state.release.wait(.1):
                            break
                except (BrokenPipeError, ConnectionResetError):
                    pass
            self.close_connection = True
            return
        status, body = 200, None
        if scenario.startswith('http'):
            status = int(scenario[4:])
            # HTTP and API codes deliberately differ in one scenario.
            code = 401 if state.different_code else status
            error = {'ok': False, 'error_code': code,
                     'description': 'useful diagnostic ' + TOKEN + '\x1b[31m ' + WEBHOOK}
            if state.retry != 'absent':
                error['parameters'] = {'retry_after': state.retry}
            if state.invalid_error_code:
                error['error_code'] = '400'
            body = json.dumps(error).encode()
        elif scenario in ('empty', 'malformed', 'array', 'null', 'multiple', 'string_ok', 'bad_result',
                          'missing_ok', 'false200', 'contradictory', 'rejection200', 'missing_description',
                          'html500', 'redirect', 'secrets'):
            body, status = {
                'empty': (b'', 200), 'malformed': (b'{bad json\n\n', 200),
                'array': (b'[]', 200), 'null': (b'null', 200),
                'multiple': (b'{"ok":true,"result":true}\n{"ok":true,"result":true}', 200),
                'string_ok': (b'{"ok":"true","result":true}', 200),
                'bad_result': (b'{"ok":true,"result":{}}', 200),
                'missing_ok': (b'{"result":true}', 200),
                'false200': (b'{"ok":false,"error_code":400}', 200),
                'contradictory': (b'{"ok":true,"result":true,"error_code":500,"description":"failure"}', 200),
                'rejection200': (b'{"ok":false,"error_code":401,"description":"useful rejection"}', 200),
                'missing_description': (b'{"ok":false,"error_code":400}', 400),
                'html500': (b'<html>proxy failed</html>\n\n', 500),
                'redirect': (b'redirect', 302),
                'secrets': (('useful ' + TOKEN + ' ' + TOKEN.replace(':', '%3a') + ' ' +
                             ''.join('\\u%04x' % ord(c) for c in TOKEN) +
                             ' ' + WEBHOOK + ' test-configuration-secret\n\n').encode(), 500),
            }[scenario]
        if body is None:
            if method == 'getMe':
                result = {'id': 123, 'first_name': 'Test', 'username': 'test'}
            elif method == 'getWebhookInfo':
                result = {'url': WEBHOOK if state.webhook else ''}
            else:
                state.effects.append((role, method))
                result = True
            body = json.dumps({'ok': True, 'result': result}).encode()
        try:
            self.send_response(status)
            if status == 302:
                self.send_header('Location', 'https://unexpected.invalid/')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class MockAPI:
    def __init__(self):
        self.scenario = 'success'
        self.target = ('source', 'deleteWebhook')
        self.occurrence = 1
        self.different_code = False
        self.invalid_error_code = False
        self.retry = 7
        self.webhook = True
        self.calls, self.effects = [], []
        self.entered, self.release = threading.Event(), threading.Event()
        self.servers, self.threads = [], []
        for role in ('source', 'target'):
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            server.daemon_threads = True
            server.role, server.state = role, self
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            self.servers.append(server)
            self.threads.append(thread)
            thread.start()

    @property
    def source_url(self):
        return 'http://127.0.0.1:%d' % self.servers[0].server_port

    @property
    def target_url(self):
        return 'http://127.0.0.1:%d' % self.servers[1].server_port

    def close(self):
        self.release.set()
        for server in self.servers:
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=5)


# Generated only into a private test PATH. Every request is checked before
# exec; this wrapper cannot silently fall through to Telegram or another host.
CURL_WRAPPER = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if not args or args[0] != '-q':
    raise SystemExit('curl isolation: -q must be first')
if any(flag in args for flag in ('-L', '--location', '--location-trusted', '--fail', '--fail-with-body', '-k', '--insecure')):
    raise SystemExit('curl isolation: forbidden option')
if args[args.index('--retry') + 1] != '0':
    raise SystemExit('curl isolation: retries forbidden')
urls = [(i, arg) for i, arg in enumerate(args) if arg.startswith(('https://', 'http://'))]
if len(urls) != 1:
    raise SystemExit('curl isolation: exactly one URL required')
i, url = urls[0]
role = None
for name, base in (('source', 'https://api.telegram.org'), ('target', os.environ['SELF_URL'])):
    prefix = base + '/bot12345:SYNTHETIC_TOKEN/'
    if url.startswith(prefix) and url[len(prefix):] in ('getMe', 'getWebhookInfo', 'deleteWebhook', 'logOut', 'setWebhook'):
        role, method = name, url[len(prefix):]
        break
if role is None:
    raise SystemExit('curl isolation: unexpected endpoint or token')
with open(os.environ['ARGLOG'], 'a') as log:
    log.write(json.dumps({'role': role, 'method': method, 'args': args}) + '\n')
if os.environ.get('FAKE_METHOD') == role + ':' + method:
    Path(args[args.index('--output') + 1]).write_bytes(os.environ.get('FAKE_BODY', '').encode())
    sys.stdout.write(os.environ.get('FAKE_STATUS', '000'))
    sys.stderr.write(os.environ.get('FAKE_STDERR', 'transport failure 12345:SYNTHETIC_TOKEN'))
    raise SystemExit(int(os.environ.get('FAKE_EXIT', '7')))
base = os.environ['SOURCE_URL' if role == 'source' else 'TARGET_URL']
args[i] = base + '/bot12345:SYNTHETIC_TOKEN/' + method
os.execv(os.environ['REAL_CURL'], [os.environ['REAL_CURL']] + args)
'''


class StalledTLS:
    """Accept TCP but never complete TLS; no external IP or CA exceptions."""
    def __init__(self):
        self.socket = socket.socket()
        self.socket.bind(('127.0.0.1', 0))
        self.socket.listen(1)
        self.socket.settimeout(.2)
        self.port = self.socket.getsockname()[1]
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                self.stop.wait(4)

    def close(self):
        self.stop.set()
        self.socket.close()
        self.thread.join(timeout=5)
