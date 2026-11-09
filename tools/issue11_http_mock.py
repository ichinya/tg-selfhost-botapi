"""Loopback-only stateful transport fixtures for the standalone Bash helper."""
import json
import argparse
from pathlib import Path
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

TOKEN = '12345:SYNTHETIC_TOKEN'
WEBHOOK = 'https://example.invalid/private-hook'
METHODS = ('probe', 'getMe', 'getWebhookInfo', 'deleteWebhook', 'logOut', 'setWebhook')
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
        method = 'probe' if self.path == '/' else self.path.rsplit('/', 1)[-1]
        if role == 'sink':
            state.calls.append((role, method))
            self.send_error(404)
            return
        if method not in METHODS or (method != 'probe' and self.path != '/bot' + TOKEN + '/' + method):
            self.send_error(400)
            return
        fields = parse_qs(self.rfile.read(int(self.headers.get('Content-Length', '0'))).decode())
        state.calls.append((role, method))
        state.persist()
        targeted = (role, method) == state.target and state.calls.count((role, method)) == state.occurrence
        scenario = state.scenario if targeted else 'success'
        if targeted and scenario not in ('lost', 'lost_no_effect', 'partial', 'headers_only', 'delayed', 'slow', 'barrier'):
            state.entered.set()
        if scenario in ('lost', 'lost_no_effect', 'partial', 'headers_only', 'delayed', 'slow', 'barrier'):
            if scenario != 'lost_no_effect':
                state.apply_effect(role, method, fields)
            state.entered.set()
            if scenario == 'barrier':
                state.release.wait(12)
            elif scenario == 'delayed':
                state.release.wait(2)
            elif scenario in ('partial', 'headers_only', 'slow'):
                self.send_response(200)
                self.send_header('Content-Length', '10000')
                self.end_headers()
                try:
                    if scenario != 'headers_only':
                        self.wfile.write(b'{"ok":true,"result":true}')
                        self.wfile.flush()
                    if scenario == 'slow':
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
            error = {'ok': False, 'error_code': 401 if state.different_code else status,
                     'description': 'useful diagnostic ' + TOKEN + '\x1b[31m ' + WEBHOOK}
            if state.retry != 'absent':
                error['parameters'] = {'retry_after': state.retry}
            if state.invalid_error_code:
                error['error_code'] = '400'
            body = json.dumps(error).encode()
        elif scenario != 'success':
            body, status = {
                'empty': (b'', 200), 'malformed': (b'{bad json\n\n', 200),
                'array': (b'[]', 200), 'null': (b'null', 200), 'scalar': (b'42', 200),
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
                             ''.join('\\u%04x' % ord(c) for c in TOKEN) + ' ' +
                             ''.join('%%%02x' % ord(c) for c in TOKEN) + ' ' + WEBHOOK +
                             ' test-configuration-secret\x1b[31m\r\n').encode(), 500),
            }[scenario]
        if body is None:
            if method == 'probe':
                status, body = 404, b'{"ok":false,"error_code":404,"description":"Not Found"}'
            else:
                state.apply_effect(role, method, fields)
                result = True
                if method == 'getMe':
                    result = {'id': 123, 'first_name': 'Test ' + TOKEN, 'username': 'test'}
                elif method == 'getWebhookInfo':
                    result = {'url': state.target_webhook if role == 'target' else WEBHOOK if state.webhook else ''}
                body = json.dumps({'ok': True, 'result': result}).encode()
        try:
            self.send_response(status)
            if status == 302:
                self.send_header('Location', state.sink_url)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class MockAPI:
    def __init__(self, state_path=None):
        self.state_path = Path(state_path) if state_path else None
        self.state_lock = threading.RLock()
        self.scenario, self.target, self.occurrence = 'success', ('source', 'deleteWebhook'), 1
        self.different_code = self.invalid_error_code = False
        self.retry, self.webhook, self.target_webhook = 7, True, ''
        self.calls, self.effects = [], []
        self.pending_updates, self.drop_count = ['old'], 0
        self.source_pending_updates, self.source_drop_count = ['old-source'], 0
        self.entered, self.release = threading.Event(), threading.Event()
        self.servers, self.threads = [], []
        for role in ('source', 'target', 'sink'):
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            server.daemon_threads = True
            server.role, server.state = role, self
            thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
            self.servers.append(server)
            self.threads.append(thread)
            thread.start()
        self.persist()

    def persist(self):
        """Commit remote evidence before the handler loses its reply."""
        if self.state_path:
            with self.state_lock:
                record = dict(calls=self.calls, effects=self.effects,
                              target_webhook=self.target_webhook,
                              pending_updates=self.pending_updates, drop_count=self.drop_count,
                              source_pending_updates=self.source_pending_updates,
                              source_drop_count=self.source_drop_count)
                temporary = self.state_path.with_suffix('.tmp')
                temporary.write_text(json.dumps(record), encoding='utf-8')
                temporary.replace(self.state_path)

    def apply_effect(self, role, method, fields):
        if method in MUTATIONS:
            self.effects.append((role, method))
        if role == 'target' and method == 'setWebhook':
            self.target_webhook = fields['url'][0]
            if fields.get('drop_pending_updates') == ['true']:
                self.pending_updates.clear()
                self.drop_count += 1
        if role == 'source' and method == 'deleteWebhook' and fields.get('drop_pending_updates') == ['true']:
            self.source_pending_updates.clear()
            self.source_drop_count += 1
        self.persist()

    @property
    def source_url(self):
        return 'http://127.0.0.1:%d' % self.servers[0].server_port

    @property
    def target_url(self):
        return 'http://127.0.0.1:%d' % self.servers[1].server_port

    @property
    def sink_url(self):
        return 'http://127.0.0.1:%d' % self.servers[2].server_port

    def close(self):
        self.release.set()
        for server in self.servers:
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=2)


# The PATH wrapper admits only synthetic loopback endpoints, including injected
# failures; no request can fall through to Telegram or a redirect destination.
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
configs = [args[i + 1] for i, arg in enumerate(args) if arg == '--config' and i + 1 < len(args)]
for config in configs:
    for line in Path(config).read_text().splitlines():
        if line.startswith('url = '):
            urls.append((None, json.loads(line[6:])))
if len(urls) != 1 or len(configs) > 1:
    raise SystemExit('curl isolation: exactly one URL required')
i, url = urls[0]
role = None
for name, base in (('source', os.environ['SOURCE_URL']), ('target', os.environ['SELF_URL'])):
    prefix = base + '/bot12345:SYNTHETIC_TOKEN/'
    if url == base + '/' and name == 'target':
        role, method = name, 'probe'
        break
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
rewritten = base + '/' if method == 'probe' else base + '/bot12345:SYNTHETIC_TOKEN/' + method
if configs:
    Path(configs[0]).write_text('url = ' + json.dumps(rewritten) + '\n')
else:
    args[i] = rewritten
os.execv(os.environ['REAL_CURL'], [os.environ['REAL_CURL']] + args)
'''


class StalledTLS:
    """Accept TCP but never complete TLS; no external address or CA exception."""
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', default='lost',
                        choices=('success', 'http400', 'http429', 'http500', 'html500',
                                 'malformed', 'lost', 'lost_no_effect', 'partial', 'delayed', 'slow'))
    parser.add_argument('--role', choices=('source', 'target'), default='source')
    parser.add_argument('--method', choices=METHODS, default='logOut')
    parser.add_argument('--state-file', type=Path, required=True)
    args = parser.parse_args()
    mock = MockAPI(args.state_file)
    mock.scenario, mock.target = args.scenario, (args.role, args.method)
    print(json.dumps(dict(source=mock.source_url, target=mock.target_url, sink=mock.sink_url,
                          state_file=str(args.state_file.resolve()))), flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        mock.close()
