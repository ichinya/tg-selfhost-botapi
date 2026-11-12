"""Bounded, opt-in file_id gateway. Stdlib only; one operator-configured bot per process."""
import argparse
from dataclasses import dataclass, field
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import queue
import re
import socket
import sys
import threading
import time

try:
    from .file_access import Root, FileAccessError, UnsupportedPlatform, overlaps
    from .file_contract import Binding, ContractError, UpstreamError, MAX_JSON, file_id_value, get_file, unique_object, read_private_file
except ImportError:
    from file_access import Root, FileAccessError, UnsupportedPlatform, overlaps
    from file_contract import Binding, ContractError, UpstreamError, MAX_JSON, file_id_value, get_file, unique_object, read_private_file

MAX_HEADERS, CLIENT_TIMEOUT, WORKERS, WAITING = 16384, 30, 4, 8
CREDENTIAL = re.compile(r'[A-Za-z0-9._~-]{32,256}\Z')


@dataclass(repr=False)
class Configuration:
    credential: str = field(repr=False)
    binding: Binding = field(repr=False)
    root: Root = field(repr=False)

    def authorize(self, values):
        if len(values) != 1 or not values[0].startswith('Bearer '):
            return False
        candidate = values[0][7:]
        return bool(CREDENTIAL.fullmatch(candidate) and hmac.compare_digest(candidate, self.credential))

    def close(self):
        self.root.close()


def load_configuration(env):
    bot_path = env['DOWNLOAD_BOT_TOKEN_FILE']
    auth_path = env['DOWNLOAD_AUTH_TOKEN_FILE']
    media = env.get('DOWNLOAD_MEDIA_ROOT', '/var/lib/telegram-bot-api-files')
    if overlaps(media, bot_path) or overlaps(media, auth_path):
        raise ContractError('secret/media overlap')
    bot, bot_info = read_private_file(bot_path, 256)
    auth, auth_info = read_private_file(auth_path, 256)
    credential = auth.decode('ascii').strip()
    token = bot.decode('ascii').strip()
    if not CREDENTIAL.fullmatch(credential) or hmac.compare_digest(credential, token):
        raise ContractError('invalid independent credential')
    for name, default in (('DOWNLOAD_TEST_DC', 'false'), ('DOWNLOAD_COLON_LAYOUT', 'true')):
        if env.get(name, default) not in ('true', 'false'):
            raise ContractError('invalid boolean')
    binding = Binding(token, env.get('DOWNLOAD_BOTAPI_ENDPOINT', 'http://botapi:8081'), media,
                      env['DOWNLOAD_BOT_ROOT'], test_dc=env.get('DOWNLOAD_TEST_DC', 'false') == 'true',
                      colon=env.get('DOWNLOAD_COLON_LAYOUT', 'true') == 'true')
    root = Root(binding.bot_root, [(i.st_dev, i.st_ino) for i in (bot_info, auth_info)])
    return Configuration(credential, binding, root)


class HeaderLimit(Exception):
    pass


class HeaderReader:
    def __init__(self, raw, connection):
        self.raw, self.connection = raw, connection
        self.deadline = time.monotonic() + CLIENT_TIMEOUT
        self.total = 0
        self.headers = True
        self.expired = False
        self.timer = threading.Timer(CLIENT_TIMEOUT, self.expire)
        self.timer.daemon = True
        self.timer.start()

    def expire(self):
        self.expired = True
        try:
            self.connection.shutdown(socket.SHUT_RD)
        except OSError:
            pass

    def complete(self):
        self.headers = False
        self.timer.cancel()

    def readline(self, limit=-1):
        if not self.headers:
            return self.raw.readline(limit)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise HeaderLimit()
        self.connection.settimeout(remaining)
        maximum = min(limit if limit > 0 else MAX_HEADERS + 1, MAX_HEADERS + 1 - self.total)
        line = self.raw.readline(maximum)
        self.total += len(line)
        if self.expired or self.total > MAX_HEADERS:
            raise HeaderLimit()
        return line

    def __getattr__(self, name):
        return getattr(self.raw, name)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'Downloads'
    sys_version = ''

    def log_message(self, *_):
        # No request paths, Authorization, file IDs, or upstream diagnostics in logs.
        pass

    def setup(self):
        self.request.settimeout(CLIENT_TIMEOUT)
        super().setup()
        self.rfile = HeaderReader(self.rfile, self.connection)
        self.deadline = time.monotonic() + self.server.max_duration
        self.stream_timer = threading.Timer(self.server.max_duration, self.expire)
        self.stream_timer.daemon = True
        self.stream_timer.start()

    def expire(self):
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def finish(self):
        # A denied request can still have unread input. Flush and half-close the
        # reply, then drain a bounded amount so TCP reset does not hide 401/413.
        self.rfile.complete()
        self.stream_timer.cancel()
        try:
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_WR)
            deadline = time.monotonic() + 0.05
            remaining = MAX_HEADERS + MAX_JSON
            while remaining > 0 and time.monotonic() < deadline:
                self.connection.settimeout(max(0.001, deadline - time.monotonic()))
                chunk = self.rfile.read1(min(4096, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
        except OSError:
            pass
        finally:
            super().finish()

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except HeaderLimit:
            self.request_version = 'HTTP/1.1'
            self.command = getattr(self, 'command', '')
            self.requestline = getattr(self, 'requestline', '')
            self.error(413)
        except (OSError, ValueError):
            self.close_connection = True

    def parse_request(self):
        try:
            return super().parse_request()
        finally:
            self.rfile.complete()

    def handle_expect_100(self):
        self.error(400)
        return False

    def headers_for(self, code, size, content_type='application/json'):
        self.close_connection = True
        self.send_response(code)
        self.send_header('Content-Length', str(size))
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if code == 200:
            self.send_header('Content-Disposition', 'attachment; filename="download.bin"')
        self.send_header('Connection', 'close')
        if code == 401:
            self.send_header('WWW-Authenticate', 'Bearer')
        self.end_headers()

    def error(self, code):
        body = b'{"error":"request unavailable"}\n'
        self.headers_for(code, len(body))
        if getattr(self, 'command', '') != 'HEAD':
            self.wfile.write(body)

    def send_error(self, code, message=None, explain=None):
        if code == 501:
            code = 405
        self.error(code if code in (400, 405, 413, 414, 431, 505) else 400)

    def do_HEAD(self):
        self.error(405)

    do_GET = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_CONNECT = do_TRACE = do_HEAD

    def do_POST(self):
        started = False
        fd = -1
        try:
            if not self.server.configuration.authorize(self.headers.get_all('Authorization', [])):
                self.error(401)
                return
            if self.path != '/v1/files/download':
                self.error(400)
                return
            entry = self.server.configuration
            lengths = self.headers.get_all('Content-Length', [])
            if (self.headers.get_all('Transfer-Encoding', []) or len(lengths) != 1
                    or not re.fullmatch(r'[0-9]{1,8}', lengths[0])
                    or self.headers.get_all('Expect', [])):
                self.error(400)
                return
            if len(self.headers.get_all('Content-Type', [])) != 1 or self.headers['Content-Type'] != 'application/json':
                self.error(415)
                return
            size = int(lengths[0])
            if size > MAX_JSON:
                self.error(413)
                return
            if self.headers.get_all('Range', []):
                self.error(416)
                return
            data = bytearray()
            deadline = time.monotonic() + CLIENT_TIMEOUT
            while len(data) < size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                self.connection.settimeout(remaining)
                part = self.rfile.read1(size - len(data))
                if not part:
                    raise ContractError('incomplete body')
                data.extend(part)
            item = json.loads(data, object_pairs_hook=unique_object)
            if not isinstance(item, dict) or set(item) != {'file_id'}:
                raise ContractError('only file_id is accepted')
            file_id = file_id_value(item['file_id'])
            # Authorization and all request validation precede getFile and file I/O.
            fd, info = entry.root.open(get_file(entry.binding, file_id))
            self.connection.settimeout(CLIENT_TIMEOUT)
            started = True
            self.headers_for(200, info.st_size, 'application/octet-stream')
            remaining = info.st_size
            while remaining:
                left = self.deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError()
                self.connection.settimeout(min(CLIENT_TIMEOUT, left))
                part = os.read(fd, min(65536, remaining))
                if not part:
                    raise FileAccessError('file changed during stream')
                self.wfile.write(part)
                remaining -= len(part)
        except UpstreamError as exc:
            if not started:
                self.error(exc.status)
        except FileAccessError:
            if not started:
                self.error(404)
        except (ContractError, ValueError, UnicodeError):
            if not started:
                self.error(400)
        except (OSError, TimeoutError):
            # Disconnect/timeouts never append JSON after response bytes.
            self.close_connection = True
        finally:
            self.close_connection = True
            if fd >= 0:
                os.close(fd)


class Server(HTTPServer):
    request_queue_size = WAITING
    allow_reuse_address = True

    def __init__(self, address, configuration, workers=WORKERS, max_duration=600):
        if not 1 <= workers <= 32 or not 1 <= max_duration <= 3600:
            raise ValueError('invalid limits')
        self.configuration = configuration
        self.max_duration = max_duration
        self.slots = threading.BoundedSemaphore(workers)
        self.pending = queue.Queue(maxsize=workers)
        self.stopping = threading.Event()
        self.active = set()
        self.active_lock = threading.Lock()
        super().__init__(address, Handler)
        self.workers = [threading.Thread(target=self.worker, daemon=True) for _ in range(workers)]
        for worker in self.workers:
            worker.start()

    def process_request(self, request, address):
        try:
            if not self.slots.acquire(blocking=False):
                raise queue.Full
            self.pending.put_nowait((request, address))
        except queue.Full:
            try:
                request.settimeout(0.2)
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n'
                                b'Cache-Control: no-store\r\nConnection: close\r\n\r\n')
                # Bounded drain avoids a TCP reset hiding the 503 when input is queued.
                request.shutdown(socket.SHUT_WR)
                request.settimeout(0.01)
                request.recv(MAX_HEADERS + MAX_JSON)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)

    def worker(self):
        while not self.stopping.is_set():
            try:
                request, address = self.pending.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                with self.active_lock:
                    self.active.add(request)
                self.finish_request(request, address)
            except Exception:
                # socketserver's default error handler would expose a traceback.
                pass
            finally:
                with self.active_lock:
                    self.active.discard(request)
                self.shutdown_request(request)
                self.pending.task_done()
                self.slots.release()

    def server_close(self):
        super().server_close()
        self.stopping.set()
        with self.active_lock:
            for request in self.active:
                try: request.shutdown(socket.SHUT_RDWR)
                except OSError: pass
        while True:
            try:
                request, _ = self.pending.get_nowait()
            except queue.Empty:
                break
            self.shutdown_request(request)
            self.pending.task_done()
            self.slots.release()
        for worker in self.workers:
            worker.join(CLIENT_TIMEOUT + 66)


def main():
    config = None
    try:
        config = load_configuration(os.environ)
        workers = int(os.environ.get('DOWNLOAD_WORKERS', '4'))
        duration = int(os.environ.get('DOWNLOAD_MAX_DURATION', '600'))
        with Server(('0.0.0.0', 8083), config, workers, duration) as server:
            server.serve_forever()
    except (OSError, KeyError, ValueError, ContractError, FileAccessError):
        print('download service unavailable: check private configuration and platform', file=sys.stderr)
        return 1
    finally:
        if config:
            config.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
