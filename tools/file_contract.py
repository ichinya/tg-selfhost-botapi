"""Operator binding and bounded getFile client shared by local and remote readers."""
from dataclasses import dataclass, field
import http.client
import json
import os
import re
import socket
import stat
import threading
from urllib.parse import urlsplit

try:
    from .file_access import Root, FileAccessError, absolute_path, overlaps
except ImportError:
    from file_access import Root, FileAccessError, absolute_path, overlaps

PRIVATE_ROOTS = ('/var/lib/telegram-bot-api', '/tmp', '/run', '/etc', '/proc', '/sys', '/dev')
MAX_JSON, MAX_FILE_ID = 16384, 1024
UPSTREAM_READ_TIMEOUT = 60


class ContractError(Exception):
    pass


class UpstreamError(ContractError):
    status = 502


class UpstreamTimeout(UpstreamError):
    status = 504


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError('duplicate key')
        result[key] = value
    return result


def file_id_value(value):
    try:
        size = len(value.encode('utf-8')) if isinstance(value, str) else 0
    except UnicodeError:
        raise ContractError('invalid file_id') from None
    if (not isinstance(value, str) or not value or size > MAX_FILE_ID
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ContractError('invalid file_id')
    return value


def bot_suffix(token, test_dc=False, colon=True):
    if (not isinstance(token, str) or not re.fullmatch(r'[1-9][0-9]{4,19}:[A-Za-z0-9_-]{6,128}', token)
            or type(test_dc) is not bool or type(colon) is not bool):
        raise ContractError('invalid bot binding')
    suffix = token + (':T' if test_dc else '')
    return suffix if colon else suffix.replace(':', '~')


@dataclass(repr=False)
class Binding:
    token: str = field(repr=False)
    endpoint: str
    media_root: str
    bot_root: str
    test_dc: bool = False
    colon: bool = True
    private_roots: tuple = PRIVATE_ROOTS

    def __post_init__(self):
        try:
            if (not isinstance(self.endpoint, str) or not isinstance(self.private_roots, (list, tuple))
                    or any(not isinstance(p, str) for p in self.private_roots)):
                raise ContractError('invalid bot binding')
            media, root = absolute_path(self.media_root), absolute_path(self.bot_root)
            if root != media / bot_suffix(self.token, self.test_dc, self.colon):
                raise ContractError('invalid bot binding')
            for private in (*PRIVATE_ROOTS, *self.private_roots):
                if overlaps(str(media), private):
                    raise ContractError('private/media roots overlap')
            url = urlsplit(self.endpoint)
            if (url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password
                    or url.path not in ('', '/') or url.query or url.fragment
                    or url.hostname.lower().rstrip('.').endswith('telegram.org')
                    or any(ord(c) < 33 for c in self.endpoint)):
                raise ContractError('invalid private endpoint')
            _ = url.port
        except (ValueError, FileAccessError, TypeError):
            raise ContractError('invalid bot binding') from None

    def __repr__(self):
        return '<Binding private>'


def read_private_file(path, maximum=131072):
    """Read the pinned, single-link secret FD; never reopen a checked pathname."""
    candidate = absolute_path(str(path))
    with Root(str(candidate.parent)) as root:
        fd, info = root.open(str(candidate))
        try:
            if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o137
                    or info.st_uid not in (0, os.geteuid()) or info.st_size > maximum):
                raise ContractError('protected regular secret file required')
            with os.fdopen(fd, 'rb', closefd=False) as source:
                data = source.read(maximum + 1)
            if len(data) > maximum:
                raise ContractError('secret file too large')
            return data, info
        finally:
            os.close(fd)


def get_file(binding, file_id):
    file_id_value(file_id)
    url = urlsplit(binding.endpoint)
    cls = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
    connection = cls(url.hostname, url.port, timeout=5)
    body = json.dumps({'file_id': file_id}).encode('utf-8')
    path = '/bot' + binding.token + ('/test' if binding.test_dc else '') + '/getFile'
    response = None
    deadline = None
    expired = threading.Event()
    try:
        # http.client ignores proxy environment variables and never follows redirects.
        connection.request('POST', path, body, {'Content-Type': 'application/json', 'Connection': 'close'})
        if connection.sock is not None:
            live_socket = connection.sock
            live_socket.settimeout(UPSTREAM_READ_TIMEOUT)
            def expire():
                expired.set()
                try:
                    live_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            # Enforce an absolute read deadline, including headers and slow-drip bodies.
            deadline = threading.Timer(UPSTREAM_READ_TIMEOUT, expire)
            deadline.daemon = True
            deadline.start()
        response = connection.getresponse()
        data = response.read(MAX_JSON + 1)
        if expired.is_set():
            raise UpstreamTimeout('upstream timeout')
        if response.status != 200 or len(data) > MAX_JSON:
            raise UpstreamError('upstream unavailable')
        item = json.loads(data, object_pairs_hook=unique_object)
        if (not isinstance(item, dict) or item.get('ok') is not True
                or not isinstance(item.get('result'), dict)
                or not isinstance(item['result'].get('file_path'), str)):
            raise UpstreamError('upstream unavailable')
        return item['result']['file_path']
    except (socket.timeout, TimeoutError):
        raise UpstreamTimeout('upstream timeout') from None
    except (OSError, http.client.HTTPException, ValueError, ContractError):
        if expired.is_set():
            raise UpstreamTimeout('upstream timeout') from None
        raise UpstreamError('upstream unavailable') from None
    finally:
        if deadline is not None:
            deadline.cancel()
        if response is not None:
            response.close()
        connection.close()


def local_copy(binding, file_id, output):
    with Root(binding.bot_root) as root:
        fd, info = root.open(get_file(binding, file_id))
        try:
            remaining = info.st_size
            while remaining:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    raise FileAccessError('file changed during read')
                output.write(chunk)
                remaining -= len(chunk)
        finally:
            os.close(fd)
