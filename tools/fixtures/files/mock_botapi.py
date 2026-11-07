"""Synthetic fixture: mock only getFile; use production reader, handler and opener."""
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import stat
import sys
import subprocess
import threading
import time

sys.path.insert(0, '/app')
from tools.file_access import Root, FileAccessError
from tools.file_contract import Binding, ContractError, local_copy, read_private_file
os.umask(0o007)

MEDIA = '/var/lib/telegram-bot-api-files'
TOKENS = {'a': '12345:SYNTHETIC_A', 'b': '12345:SYNTHETIC_B'}
CREDS = {'a': 'A' * 40, 'b': 'B' * 40}
EXACT = b'EXACT_SYNTHETIC_BYTES'
CALLS = 0
CALLS_LOCK = threading.Lock()


def state_setup():
    Path('/private-state/webhooks_db.binlog').write_bytes(b'STATE_PRIVATE_CANARY')
    os.chown('/private-state/webhooks_db.binlog', 101, 101)
    os.chmod('/private-state/webhooks_db.binlog', 0o640)
    print(json.dumps({'setup': 'PASS'}))


class StateMock(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        assert Path('/private-state/webhooks_db.binlog').read_bytes() == b'STATE_PRIVATE_CANARY'
        self.send_response(404)
        self.send_header('Content-Length', '0')
        self.end_headers()


def state_serve():
    ThreadingHTTPServer(('0.0.0.0', 8081), StateMock).serve_forever()


def state_client():
    paths = ('/file', '/file/', '/file/bot12345:SYNTHETIC_A/webhooks_db.binlog',
             '/file/../webhooks_db.binlog', '/file/%2e%2e/webhooks_db.binlog',
             '/file/%252e%252e/webhooks_db.binlog', '/webhooks_db.binlog',
             '/var/lib/telegram-bot-api/webhooks_db.binlog', '//file//webhooks_db.binlog')
    for _ in range(30):
        try:
            with socket.create_connection(('state-gateway', 80), timeout=1):
                break
        except OSError:
            time.sleep(1)
    else:
        raise AssertionError('state gateway readiness')
    for path in paths:
        conn = http.client.HTTPConnection('state-gateway', 80, timeout=5)
        try:
            conn.request('GET', path)
            response = conn.getresponse()
            data = response.read()
            assert response.status in (400, 403, 404) and b'CANARY' not in data
        finally:
            conn.close()
    print(json.dumps({'state_isolation': 'PASS', 'cases': len(paths)}))


def bot_root(bot):
    return MEDIA + '/' + TOKENS[bot]


def registry(rotated=False):
    return {'bots': [dict(alias='bot-' + bot, credential=('C' * 40 if bot == 'a' and rotated else CREDS[bot]),
                         token=token, endpoint='http://botapi:8081', media_root=MEDIA, bot_root=bot_root(bot))
                     for bot, token in TOKENS.items()]}


def setup():
    os.umask(0o007)
    for path in [MEDIA, '/private-state', '/registry', '/token', '/backup']:
        os.chown(path, 101, 101)
        os.chmod(path, 0o770 if path == MEDIA else 0o750)
    for bot in TOKENS:
        root = Path(bot_root(bot))
        root.mkdir(mode=0o750, exist_ok=True)
        os.chown(root, 101, 101)
        os.chmod(root, 0o2750)
        (root / 'nested').mkdir(exist_ok=True)
    Path('/registry/downloads.config.json').write_text(json.dumps(registry()))
    Path('/token/bot-token').write_text(TOKENS['a'])
    for path in ('/registry/downloads.config.json', '/token/bot-token'):
        os.chown(path, 0, 101)
        os.chmod(path, 0o640)


def decorate():
    root = Path(bot_root('a'))
    # Assert real writer ownership before any helper touches generated files.
    for bot in TOKENS:
        info = Path(bot_root(bot) + '/tdlib-documents/fixture.bin').stat()
        assert (info.st_uid, info.st_gid) == (101, 101) and info.st_mode & 0o007 == 0
    for name, target in [('leaf', '/private-state/webhooks_db.binlog'),
                         ('parent', '/private-state'), ('foreign', bot_root('b')),
                         ('magic', '/proc/self/fd/0')]:
        (root / name).symlink_to(target)
    os.mkfifo(root / 'fifo')
    special = socket.socket(socket.AF_UNIX)
    special.bind(str(root / 'socket'))
    special.close()
    os.mknod(root / 'device', stat.S_IFCHR | 0o660, os.makedev(1, 3))
    os.link(root / 'tdlib-documents/fixture.bin', root / 'hardlink')
    # Keep the positive fixture single-linked; hardlink case has its own inode.
    (root / 'hardlink').unlink()
    (root / 'hard-source').write_bytes(b'HARDLINK_CANARY')
    os.link(root / 'hard-source', root / 'hardlink')
    with (root / 'large.bin').open('wb') as target:
        for _ in range(1024):
            target.write(b'Z' * 65536)
    for name in ('hard-source', 'hardlink', 'large.bin', 'nested', 'fifo', 'socket', 'device'):
        os.chown(root / name, 101, 101)
    (root / 'unreadable').write_bytes(b'UNREADABLE_CANARY')
    (root / 'unreadable').chmod(0)
    shutil.copytree('/private-state', '/backup/state', dirs_exist_ok=True)
    Path('/backup/hash').write_text(hashlib.sha256(Path('/private-state/webhooks_db.binlog').read_bytes()).hexdigest())
    shutil.copy2(root / 'tdlib-documents/fixture.bin', '/backup/media.bin')


def selected_path(bot, file_id):
    root = bot_root(bot)
    return {'fixture': root + '/tdlib-documents/fixture.bin', 'foreign': bot_root('b') + '/tdlib-documents/fixture.bin',
            'state': '/private-state/webhooks_db.binlog', 'legacy': '/var/lib/telegram-bot-api/cache.bin',
            'temp': '/tmp/private', 'log': '/private-state/server.log', 'secrets': '/run/secrets/downloads.config.json',
            'outside': '/etc/passwd', 'relative': 'tdlib-documents/fixture.bin',
            'traversal': root + '/documents/../../secret', 'prefix': root + '-other/fixture',
            'leaf': root + '/leaf', 'parent': root + '/parent/webhooks_db.binlog',
            'magic': root + '/magic', 'hardlink': root + '/hardlink', 'directory': root + '/documents',
            'fifo': root + '/fifo', 'socket': root + '/socket', 'device': root + '/device',
            'unreadable': root + '/unreadable',
            'missing': root + '/missing', 'encoded': root + '/%2e%2e/private',
            'double-encoded': root + '/%252e%252e/private', 'large': root + '/large.bin'}.get(file_id, root + '/missing')


class Mock(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        global CALLS
        with CALLS_LOCK:
            CALLS += 1
        try:
            token = self.path.split('/')[1][3:]
            bot = next(b for b, t in TOKENS.items() if t == token)
            value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))['file_id']
            if value == 'redirect':
                self.send_response(302)
                self.send_header('Location', 'http://forbidden.invalid')
                data = b'PRIVATE_UPSTREAM_CANARY'
            elif value == 'malformed':
                self.send_response(200)
                data = b'PRIVATE_UPSTREAM_CANARY'
            elif value == 'slow':
                time.sleep(61)
                self.send_response(200)
                data = b'{}'
            else:
                self.send_response(200)
                data = json.dumps({'ok': True, 'result': {'file_path': selected_path(bot, value)}}).encode()
        except Exception:
            self.send_response(401)
            data = b'{"ok":false}'
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except OSError:
            pass

    def do_GET(self):
        if self.path != '/__calls':
            self.send_error(404)
            return
        with CALLS_LOCK:
            data = json.dumps({'calls': CALLS}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def local():
    token, _ = read_private_file('/run/local-token/bot-token', 256)
    binding = Binding(token.decode(), 'http://botapi:8081', MEDIA, bot_root('a'))
    env = {**os.environ, 'BOT_TOKEN_FILE': '/run/local-token/bot-token',
           'BOTAPI_ENDPOINT': 'http://botapi:8081', 'BOT_MEDIA_ROOT': MEDIA, 'BOT_ROOT': bot_root('a')}
    actual = subprocess.run([sys.executable, '/app/examples/files/local_reader.py', 'fixture'],
                            env=env, capture_output=True, timeout=70)
    assert actual.returncode == 0 and actual.stdout == EXACT and not actual.stderr
    result = io.BytesIO()
    local_copy(binding, 'fixture', result)
    assert result.getvalue() == EXACT
    for file_id in ('foreign', 'state', 'legacy', 'temp', 'log', 'secrets', 'outside', 'relative',
                    'traversal', 'prefix', 'leaf', 'parent', 'magic', 'hardlink', 'directory', 'fifo',
                    'socket', 'device', 'unreadable', 'missing', 'encoded', 'double-encoded'):
        try:
            local_copy(binding, file_id, io.BytesIO())
        except (FileAccessError, ContractError):
            continue
        raise AssertionError('local denial case failed')
    assert not Path(bot_root('b')).exists() and not Path('/private-state').exists()
    info = Path(bot_root('a') + '/tdlib-documents/fixture.bin').stat()
    assert info.st_uid == 101 and info.st_gid == 101 and info.st_mode & 0o007 == 0
    try:
        Path(bot_root('a') + '/write-probe').write_bytes(b'x')
    except OSError:
        pass
    else:
        raise AssertionError('reader mount writable')
    print(json.dumps({'local': 'PASS', 'uid': os.getuid(), 'kernel': os.uname().release,
                      'python': sys.version.split()[0], 'negative_cases': 22}))


def remote(rotated=False):
    context = ssl.create_default_context(cafile='/tls/fullchain.pem')
    credential = 'C' * 40 if rotated else CREDS['a']

    def request(file_id='fixture', auth=credential, alias='bot-a', method='POST', extra=None, raw=None, target=None):
        conn = http.client.HTTPSConnection('downloads-tls', 443, timeout=70, context=context)
        headers = {'Content-Type': 'application/json'}
        if auth is not None:
            headers['Authorization'] = 'Bearer ' + auth
        headers.update(extra or {})
        try:
            conn.request(method, target or '/downloads/' + alias, body=raw if raw is not None else json.dumps({'file_id': file_id}),
                         headers=headers)
            response = conn.getresponse()
            data = response.read()
            assert response.getheader('Cache-Control') is not None
            if response.status != 200:
                assert b'CANARY' not in data and TOKENS['a'].encode() not in data
                assert MEDIA.encode() not in data
            return response.status, data
        finally:
            conn.close()

    assert request() == (200, EXACT)
    assert request(auth=CREDS['b'], alias='bot-b') == (200, EXACT)
    for kwargs, expected in [({'auth': None}, 401), ({'auth': 'wrong'}, 401),
            ({'auth': CREDS['b']}, 403), ({'alias': 'unknown'}, 403),
            ({'auth': None, 'extra': {'X-Telegram-Bot-Token': TOKENS['a']}}, 401),
            ({'method': 'HEAD'}, 405), ({'extra': {'Range': 'bytes=0-7'}}, 416),
            ({'raw': '{"file_id":"fixture","path":"/etc/passwd"}'}, 400),
            ({'raw': '{"file_id":"fixture","file_id":"state"}'}, 400),
            ({'raw': 'x' * 16385}, 413), ({'file_id': 'redirect'}, 502),
            ({'file_id': 'malformed'}, 502)]:
        assert request(**kwargs)[0] == expected, 'remote protocol case failed'
    for file_id in ('foreign', 'state', 'legacy', 'temp', 'log', 'secrets', 'outside', 'relative',
                    'traversal', 'prefix', 'leaf', 'parent', 'magic', 'hardlink', 'directory', 'fifo',
                    'socket', 'device', 'unreadable', 'missing', 'encoded', 'double-encoded'):
        assert request(file_id)[0] == 404, 'remote path denial case failed'
    for target in ('/file', '/file/', '/file/webhooks_db.binlog', '/%66ile/webhooks_db.binlog',
                   '/x/../file/webhooks_db.binlog', '/file/%252e%252e/private'):
        for method in ('POST', 'GET', 'HEAD'):
            assert request(target=target, method=method)[0] == 404
    if rotated:
        assert request(auth=CREDS['a'])[0] == 401
    else:
        assert request('slow')[0] == 504
    # Stream a 64 MiB file without buffering the client response in RAM.
    conn = http.client.HTTPSConnection('downloads-tls', 443, timeout=30, context=context)
    conn.request('POST', '/downloads/bot-a', json.dumps({'file_id': 'large'}),
                 {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + credential})
    response = conn.getresponse()
    total = 0
    while chunk := response.read(65536):
        assert chunk == b'Z' * len(chunk)
        total += len(chunk)
    assert response.status == 200 and total == 64 * 1024 * 1024
    conn.close()
    # Disconnect midstream, then ensure another request is served normally.
    conn = http.client.HTTPSConnection('downloads-tls', 443, timeout=30, context=context)
    conn.request('POST', '/downloads/bot-a', '{"file_id":"large"}',
                 {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + credential})
    response = conn.getresponse()
    assert response.status == 200
    response.read(1024)
    response.close()
    conn.close()
    assert request() == (200, EXACT)
    # Untrusted clients cannot silently disable certificate validation.
    bad = http.client.HTTPSConnection('downloads-tls', 443, timeout=5)
    try:
        bad.request('GET', '/')
    except ssl.SSLCertVerificationError:
        pass
    else:
        raise AssertionError('untrusted TLS unexpectedly accepted')
    finally:
        bad.close()
    try:
        socket.create_connection(('botapi', 8081), timeout=1).close()
    except OSError:
        pass
    else:
        raise AssertionError('remote network can reach private Bot API')
    print(json.dumps({'remote_tls': 'PASS', 'rotation': 'PASS' if rotated else 'NOTRUN', 'large_bytes': total}))


def overload():
    sockets = []
    try:
        for _ in range(12):
            sock = socket.create_connection(('downloads', 8083), timeout=3)
            sock.sendall(b'POST /downloads/bot-a HTTP/1.1\r\nHost: fixture\r\nAuthorization: Bearer '
                         + CREDS['a'].encode() + b'\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{')
            sockets.append(sock)
            time.sleep(0.05)
        with socket.create_connection(('downloads', 8083), timeout=3) as sock:
            sock.sendall(b'GET / HTTP/1.1\r\nHost: fixture\r\n\r\n')
            response = http.client.HTTPResponse(sock)
            response.begin()
            assert response.status == 503
            response.read()
    finally:
        for sock in sockets:
            sock.close()
    print(json.dumps({'bounded_queue': 'PASS'}))


def auth_counters():
    def count():
        conn = http.client.HTTPConnection('botapi', 8081, timeout=5)
        try:
            conn.request('GET', '/__calls')
            response = conn.getresponse()
            assert response.status == 200
            return json.loads(response.read())['calls']
        finally:
            conn.close()
    before = count()
    for host, port in (('downloads', 8083), ('downloads-gateway', 80)):
        for auth, alias, expected in ((None, 'bot-a', 401), ('wrong', 'bot-a', 401),
                                       (CREDS['b'], 'bot-a', 403), (CREDS['a'], 'unknown', 403)):
            conn = http.client.HTTPConnection(host, port, timeout=5)
            try:
                headers = {'Content-Type': 'application/json'}
                if auth:
                    headers['Authorization'] = 'Bearer ' + auth
                conn.request('POST', '/downloads/' + alias, '{"file_id":"fixture"}', headers)
                response = conn.getresponse()
                assert response.status == expected and b'CANARY' not in response.read()
            finally:
                conn.close()
        for extra in (b'Authorization: Bearer ' + CREDS['a'].encode() + b'\r\n',
                      b'Content-Length: 2\r\n', b'Transfer-Encoding: chunked\r\n'):
            with socket.create_connection((host, port), timeout=5) as sock:
                sock.sendall(b'POST /downloads/bot-a HTTP/1.1\r\nHost: fixture\r\nAuthorization: Bearer '
                             + CREDS['a'].encode() + b'\r\nContent-Type: application/json\r\nContent-Length: 2\r\n'
                             + extra + b'\r\n{}')
                response = http.client.HTTPResponse(sock)
                response.begin()
                assert response.status in (400, 401) and b'CANARY' not in response.read()
    assert count() == before, 'authorization/framing denial reached getFile'
    print(json.dumps({'auth_before_getFile': 'PASS', 'backend_and_proxy': 'PASS'}))


def mountcheck():
    nested = Path(bot_root('a')) / 'nested'
    (nested / 'canary').write_bytes(b'NESTED_MOUNT_CANARY')
    with Root(bot_root('a')) as root:
        try:
            root.open(str(nested / 'canary'))
        except FileAccessError:
            pass
        else:
            raise AssertionError('nested mount accepted')
    with Root(str(nested)) as root:
        fd, info = root.open(str(nested / 'canary'))
        os.close(fd)
        assert info.st_size == 19
    print(json.dumps({'no_xdev': 'PASS', 'root_mount': 'PASS'}))


def rotate():
    Path('/registry/downloads.config.json').write_text(json.dumps(registry(True)))
    print(json.dumps({'registry_changed': 'PASS'}))


def ready():
    context = ssl.create_default_context(cafile='/tls/fullchain.pem')
    for _ in range(30):
        conn = http.client.HTTPSConnection('downloads-tls', 443, timeout=1, context=context)
        try:
            conn.request('HEAD', '/downloads/bot-a')
            response = conn.getresponse()
            if response.status == 405:
                response.read()
                return
        except OSError:
            pass
        finally:
            conn.close()
        time.sleep(1)
    raise AssertionError('TLS fixture readiness deadline')


def rollback():
    current = hashlib.sha256(Path('/private-state/webhooks_db.binlog').read_bytes()).hexdigest()
    assert current == Path('/backup/hash').read_text()
    Path('/private-state/webhooks_db.binlog').write_bytes(b'SYNTHETIC_POST_UPGRADE_STATE')
    shutil.copytree('/backup/state', '/private-state', dirs_exist_ok=True)
    assert hashlib.sha256(Path('/private-state/webhooks_db.binlog').read_bytes()).hexdigest() == current
    state = Path('/private-state/webhooks_db.binlog')
    os.chown(state, 101, 101)
    media = Path(bot_root('a')) / 'tdlib-documents/fixture.bin'
    media.write_bytes(b'POST_UPGRADE_WRITER_CHANGE')
    shutil.copy2('/backup/media.bin', media)
    os.chown(media, 101, 101)
    assert media.read_bytes() == EXACT
    assert (state.stat().st_uid, state.stat().st_gid, media.stat().st_uid, media.stat().st_gid) == (101, 101, 101, 101)
    print(json.dumps({'synthetic_state_upgrade_rollback': 'PASS'}))


if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'serve':
        ThreadingHTTPServer(('0.0.0.0', 8081), Mock).serve_forever()
    elif mode == 'remote-rotated':
        remote(True)
    else:
        globals()[mode]()
