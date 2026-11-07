"""Bounded, opt-in file_id gateway. Stdlib only; private registry is operator-owned."""
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
ALIAS = re.compile(r'[a-z][a-z0-9_-]{0,31}\Z')
CREDENTIAL = re.compile(r'[A-Za-z0-9._~-]{32,256}\Z')


@dataclass(repr=False)
class Entry:
    alias: str
    credential: str = field(repr=False)
    binding: Binding = field(repr=False)
    root: Root = field(repr=False)


class Registry:
    def __init__(self, items, forbidden_inodes=()):
        self.entries = []
        try:
            if not isinstance(items, dict) or set(items) != {'bots'} or not isinstance(items['bots'], list):
                raise ContractError('invalid registry')
            if not 1 <= len(items['bots']) <= 128:
                raise ContractError('invalid registry')
            for item in items['bots']:
                required = {'alias', 'credential', 'token', 'endpoint', 'media_root', 'bot_root'}
                optional = {'test_dc', 'colon', 'private_roots'}
                if (not isinstance(item, dict) or not required <= set(item)
                        or set(item) - required - optional
                        or not isinstance(item['alias'], str) or not ALIAS.fullmatch(item['alias'])
                        or not isinstance(item['credential'], str) or not CREDENTIAL.fullmatch(item['credential'])):
                    raise ContractError('invalid registry')
                if any(e.alias == item['alias'] or hmac.compare_digest(e.credential, item['credential'])
                       for e in self.entries):
                    raise ContractError('duplicate registry identity')
                binding = Binding(**{k: v for k, v in item.items() if k not in ('alias', 'credential')})
                if any(overlaps(binding.bot_root, e.binding.bot_root) for e in self.entries):
                    raise ContractError('overlapping bot roots')
                root = Root(binding.bot_root, forbidden_inodes)
                self.entries.append(Entry(item['alias'], item['credential'], binding, root))
        except BaseException:
            self.close()
            raise

    def authorize(self, header_values, alias):
        if len(header_values) != 1 or not header_values[0].startswith('Bearer '):
            return 401, None
        candidate = header_values[0][7:]
        if not CREDENTIAL.fullmatch(candidate):
            return 401, None
        # Compare every credential before scope selection, without an early match exit.
        matched = None
        for entry in self.entries:
            if hmac.compare_digest(candidate, entry.credential):
                matched = entry
        if matched is None:
            return 401, None
        if matched.alias != alias:
            return 403, None
        return 200, matched

    def close(self):
        for entry in self.entries:
            entry.root.close()
        self.entries.clear()


def load_registry(path):
    data, info = read_private_file(path)
    items = json.loads(data, object_pairs_hook=unique_object)
    for item in items.get('bots', []) if isinstance(items, dict) else []:
        if isinstance(item, dict) and isinstance(item.get('media_root'), str):
            if overlaps(item['media_root'], str(path)):
                raise ContractError('registry must be outside media')
    return Registry(items, [(info.st_dev, info.st_ino)])


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

    def finish(self):
        # A denied request can still have unread input. Flush and half-close the
        # reply, then drain a bounded amount so TCP reset does not hide 401/413.
        self.rfile.complete()
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
            target = re.fullmatch(r'/downloads/([a-z][a-z0-9_-]{0,31})', self.path.split('?', 1)[0])
            alias = target.group(1) if target else ''
            code, entry = self.server.registry.authorize(self.headers.get_all('Authorization', []), alias)
            if code != 200:
                self.error(code)
                return
            if not target or '?' in self.path:
                self.error(400)
                return
            lengths = self.headers.get_all('Content-Length', [])
            if (self.headers.get_all('Transfer-Encoding', []) or len(lengths) != 1
                    or not re.fullmatch(r'[0-9]{1,8}', lengths[0])
                    or self.headers.get_all('Expect', [])):
                self.error(400)
                return
            if len(self.headers.get_all('Content-Type', [])) != 1 or self.headers['Content-Type'] != 'application/json':
                self.error(400)
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

    def __init__(self, address, registry):
        self.registry = registry
        self.pending = queue.Queue(maxsize=WAITING)
        self.stopping = threading.Event()
        super().__init__(address, Handler)
        self.workers = [threading.Thread(target=self.worker, daemon=True) for _ in range(WORKERS)]
        for worker in self.workers:
            worker.start()

    def process_request(self, request, address):
        try:
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
                self.finish_request(request, address)
            except Exception:
                # socketserver's default error handler would expose a traceback.
                pass
            finally:
                self.shutdown_request(request)
                self.pending.task_done()

    def server_close(self):
        super().server_close()
        self.stopping.set()
        while True:
            try:
                request, _ = self.pending.get_nowait()
            except queue.Empty:
                break
            self.shutdown_request(request)
            self.pending.task_done()
        for worker in self.workers:
            worker.join(CLIENT_TIMEOUT + 66)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--registry', required=True)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8083)
    args = parser.parse_args()
    registry = None
    try:
        registry = load_registry(args.registry)
        with Server((args.host, args.port), registry) as server:
            server.serve_forever()
    except (OSError, ValueError, ContractError, FileAccessError):
        print('download service unavailable: check private configuration and platform', file=sys.stderr)
        return 1
    finally:
        if registry:
            registry.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
