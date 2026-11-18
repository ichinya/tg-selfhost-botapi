"""Synthetic-only integration actions. Only structured summaries go to the host."""
import ctypes
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import threading
import time
import unittest
from tools.file_access import Root, FileAccessError

BASE = '/var/lib/telegram-bot-api-files'
TOKEN = '12345:SYNTHETIC_A'
ROOT = BASE + '/' + TOKEN
EXACT = b'EXACT_SYNTHETIC_BYTES'
AUTH = 'A' * 40
CALLS = 0


def setup():
    os.umask(0o007)
    for token in (TOKEN, '12345:SYNTHETIC_B'):
        path = Path('/media') / token
        path.mkdir(mode=0o770)
        os.chown(path, 101, 101)
    root = Path('/media') / TOKEN
    (root / 'small').write_bytes(EXACT)
    (root / 'empty').touch()
    with (root / 'large').open('wb') as output: output.truncate(16 * 1024 * 1024)
    other = Path('/media/12345:SYNTHETIC_B/foreign'); other.write_bytes(b'PRIVATE_CANARY')
    Path('/media/12345:SYNTHETIC_B/only-nested').write_bytes(b'PRIVATE_CANARY')
    Path('/private-state/binlog').write_bytes(b'PRIVATE_STATE_CANARY')
    (root / 'leaf').symlink_to('/private-state/binlog')
    (root / 'parent').symlink_to('/private-state', target_is_directory=True)
    (root / 'dangling').symlink_to('/missing')
    os.link(other, root / 'hardlink')
    os.mkfifo(root / 'fifo')
    (root / 'directory').mkdir()
    (root / 'nested').mkdir()
    (root / 'denied').write_bytes(b'NO_READ')
    for path in root.iterdir():
        if not path.is_symlink(): os.chown(path, 101, 101)
    (root / 'denied').chmod(0)
    for name, value in (('bot-token', TOKEN), ('auth', AUTH)):
        path = Path('/secret') / name; path.write_text(value); path.chmod(0o640); os.chown(path, 0, 101)
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-subj', '/CN=tls', '-addext', 'subjectAltName=DNS:tls,DNS:localhost',
                    '-keyout', '/tls/server.key', '-out', '/tls/server.crt'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    Path('/tls/server.crt').chmod(0o644)


class Mock(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def reply(self, item, code=200):
        body = json.dumps(item).encode(); self.send_response(code)
        self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        self.reply({'calls': CALLS} if self.path == '/stats' else {'ok': False, 'error_code': 404},
                   200 if self.path == '/stats' else 404)
    def do_POST(self):
        global CALLS
        CALLS += 1
        item = json.loads(self.rfile.read(min(int(self.headers.get('Content-Length', 0)), 4096)))
        file_id = item.get('file_id')
        if file_id == 'lost-upstream': self.close_connection = True; return
        if file_id == 'timeout': time.sleep(32)
        if file_id in ('bad-json', 'big-json', 'redirect'):
            data = b'x' * 65537 if file_id == 'big-json' else b'not-json'
            self.send_response(302 if file_id == 'redirect' else 200)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Location', 'http://untrusted.invalid/')
            self.end_headers(); self.wfile.write(data); return
        if file_id == 'unknown': self.reply({'ok': False, 'error_code': 400}); return
        paths = {'foreign': BASE + '/12345:SYNTHETIC_B/foreign', 'private': '/private-state/binlog',
                 'parent': ROOT + '/parent/binlog',
                 'traversal': ROOT + '/../12345:SYNTHETIC_B/foreign',
                 'encoded': ROOT + '/%2e%2e/foreign', 'double': ROOT + '/%252e%252e/foreign',
                 'nul': ROOT + '/small\x00', 'sibling': ROOT + '-other/small'}
        self.reply({'ok': True, 'result': {'file_path': paths.get(file_id, ROOT + '/' + str(file_id))}})


def local():
    run = subprocess.run([sys.executable, '/app/examples/files/local_reader.py', 'small'], capture_output=True)
    assert run.returncode == 0 and run.stdout == EXACT
    with Root(ROOT) as root:
        for name in ('leaf', 'parent/binlog', 'dangling', 'hardlink', 'fifo', 'directory', 'denied', 'missing'):
            try: root.open(ROOT + '/' + name)
            except FileAccessError: pass
            else: raise AssertionError('unsafe local file')
    assert not Path('/private-state/binlog').exists()
    assert not Path(BASE + '/12345:SYNTHETIC_B').exists()
    try: Path(ROOT + '/write').write_bytes(b'write')
    except OSError: pass
    else: raise AssertionError('media was writable')
    for path in (ROOT + '-wrong', BASE + '/12345:SYNTHETIC_B'):
        try: Root(path)
        except FileAccessError: pass
        else: raise AssertionError('unexpected root')


def calls():
    connection = http.client.HTTPConnection('botapi', 8081, timeout=3)
    connection.request('GET', '/stats'); result = json.loads(connection.getresponse().read())['calls']; connection.close()
    return result


def remote():
    context = ssl.create_default_context(cafile='/tls/server.crt')
    def request(file_id, auth=AUTH, item=None, extra_headers=None, method='POST'):
        connection = http.client.HTTPSConnection('tls', 443, context=context, timeout=40)
        body = json.dumps(item if item is not None else {'file_id': file_id})
        headers = {'Content-Type': 'application/json'}
        if auth: headers['Authorization'] = 'Bearer ' + auth
        headers.update(extra_headers or {})
        connection.request(method, '/v1/files/download', body, headers)
        response = connection.getresponse(); digest = hashlib.sha256(); count = 0
        while True:
            block = response.read(65536)
            if not block: break
            assert b'PRIVATE_CANARY' not in block and b'PRIVATE_STATE_CANARY' not in block
            digest.update(block); count += len(block)
        result = response.status, digest.hexdigest(), count
        assert response.getheader('Cache-Control') == 'no-store'
        connection.close(); return result
    for _ in range(40):
        try:
            if request('small')[0] == 200: break
        except OSError: pass
        time.sleep(0.25)
    else: raise AssertionError('TLS readiness')
    before = calls()
    for auth in (None, 'B' * 40, TOKEN): assert request('small', auth)[0] == 401
    assert request('small', None, extra_headers={'X-Telegram-Bot-Token': TOKEN})[0] == 401
    for file_id in ('/private-state/binlog', '../foreign', '%2e%2e', '%252e%252e', 'https://other/file'):
        assert request(file_id)[0] == 400
    assert request('small', extra_headers={'Range': 'bytes=0-1'})[0] == 416
    assert request('small', extra_headers={'Content-Type': 'text/plain'})[0] == 415
    assert request('small', method='HEAD')[0] == 405
    assert calls() == before
    assert request('small') == (200, hashlib.sha256(EXACT).hexdigest(), len(EXACT))
    assert request('empty') == (200, hashlib.sha256(b'').hexdigest(), 0)
    digest = hashlib.sha256()
    for _ in range(256): digest.update(bytes(65536))
    assert request('large') == (200, digest.hexdigest(), 16 * 1024 * 1024)
    for file_id in ('unknown', 'foreign', 'private', 'traversal', 'encoded', 'double', 'nul',
                    'sibling', 'leaf', 'parent', 'dangling', 'hardlink', 'fifo', 'directory', 'denied', 'missing'):
        assert request(file_id)[0] == 404, file_id
    assert request('small', item={'file_id': 'small', 'path': '/private-state/binlog'})[0] == 400
    for file_id in ('bad-json', 'big-json', 'redirect', 'lost-upstream'):
        assert request(file_id)[0] == 502
    assert request('timeout')[0] == 504
    client = '/app/examples/files/remote_client.py'
    env = {**os.environ, 'SSL_CERT_FILE': '/tls/server.crt', 'DOWNLOAD_AUTH_TOKEN': AUTH,
           'DOWNLOAD_URL': 'https://tls/v1/files/download'}
    env.pop('DOWNLOAD_AUTH_TOKEN_FILE', None)
    result = subprocess.run([sys.executable, client, 'small'], env=env, capture_output=True, timeout=10)
    assert result.returncode == 0 and result.stdout == EXACT
    # A real TLS peer ending the body after its headers must fail the shipped CLI.
    class Truncate(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200); self.send_header('Content-Length', '100')
            self.end_headers(); self.wfile.write(b'short')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Truncate)
    tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls_context.load_cert_chain('/tls/server.crt', '/tls/server.key')
    server.socket = tls_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        env['DOWNLOAD_URL'] = f'https://localhost:{server.server_port}/v1/files/download'
        result = subprocess.run([sys.executable, client, 'small'], env=env, capture_output=True, timeout=10)
        assert result.returncode != 0 and b'download unavailable' in result.stderr
    finally:
        server.shutdown(); server.server_close(); thread.join(2)
    # The primary API proxy remains usable and rejects its old file interface.
    connection = http.client.HTTPConnection('gateway', 80, timeout=3)
    connection.request('GET', '/file/bot' + TOKEN + '/binlog')
    response = connection.getresponse(); assert response.status == 404; response.read(); connection.close()
    connection = http.client.HTTPConnection('gateway', 80, timeout=3)
    connection.request('POST', '/bot' + TOKEN + '/getFile', json.dumps({'file_id': 'small'}),
                       {'Content-Type': 'application/json'})
    response = connection.getresponse(); item = json.loads(response.read()); connection.close()
    assert response.status == 200 and item['result']['file_path'] == ROOT + '/small'


def kernel():
    suite = unittest.TestSuite()
    for name in ('test_file_access.py', 'test_download_server.py'):
        suite.addTests(unittest.defaultTestLoader.discover('/app/tools', pattern=name))
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=0).run(suite)
    if not result.wasSuccessful() or result.skipped:
        raise AssertionError('mandatory Linux tests failed or skipped')


def mountcheck():
    # Same-device bind mounts must be rejected by openat2, not merely st_dev.
    source = '/media/12345:SYNTHETIC_B'
    target = '/media/' + TOKEN + '/nested'
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.mount(source.encode(), target.encode(), None, 4096, None) != 0:
        raise RuntimeError('required bind-mount probe unavailable')
    try:
        with Root('/media/' + TOKEN) as root:
            try: root.open(target + '/only-nested')
            except FileAccessError: pass
            else: raise AssertionError('nested bind accepted')
    finally:
        assert libc.umount2(target.encode(), 0) == 0


if __name__ == '__main__':
    action = sys.argv[1]
    if action == 'upstream': ThreadingHTTPServer(('0.0.0.0', 8081), Mock).serve_forever()
    else:
        try:
            {'setup': setup, 'local': local, 'remote': remote, 'kernel': kernel, 'mountcheck': mountcheck}[action]()
            print(json.dumps({'case': action, 'status': 'PASS'}))
        except Exception:
            print(json.dumps({'case': action, 'status': 'FAIL'})); sys.exit(1)
