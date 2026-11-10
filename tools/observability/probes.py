"""Fixed-target HTTP, no proxy environment, redirects or upstream diagnostics."""
import ipaddress
import json
import select
import socket
import time


def target(bind='0.0.0.0', port='8081'):
    if '%' in bind: raise ValueError('unsupported_bind')
    host = ipaddress.ip_address(bind.strip('[]'))
    if not str(port).isascii() or not str(port).isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError('invalid_target')
    if host.is_unspecified:
        host = ipaddress.ip_address('::1' if host.version == 6 else '127.0.0.1')
    return str(host), int(port)


def request(host, port, path='/', max_body=65536):
    """One bounded HTTP/1.0 exchange; only internally constructed paths are used."""
    deadline = time.monotonic() + 2
    raw = bytearray()
    with socket.create_connection((host, port), timeout=1) as conn:
        conn.setblocking(False)
        data = ('GET ' + path + ' HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n').encode('ascii')
        while data:
            remain = deadline - time.monotonic()
            if remain <= 0 or not select.select([], [conn], [], remain)[1]:
                raise ValueError('timeout')
            sent = conn.send(data)
            if not sent: raise ValueError('transport_error')
            data = data[sent:]
        while True:
            remain = deadline - time.monotonic()
            if remain <= 0 or not select.select([conn], [], [], remain)[0]:
                raise ValueError('timeout')
            part = conn.recv(4096)
            if not part: break
            raw.extend(part)
            if len(raw) > max_body + 8192: raise ValueError('body_limit')
    head, sep, body = bytes(raw).partition(b'\r\n\r\n')
    if not sep or len(head) > 8192 or len(body) > max_body:
        raise ValueError('invalid_response')
    import re
    lines = head.split(b'\r\n')
    match = re.fullmatch(rb'HTTP/1\.[01] ([0-9]{3})(?: [\x20-\x7e]*)?', lines[0])
    if not match: raise ValueError('invalid_response')
    headers = {}
    for line in lines[1:]:
        key, sep, value = line.partition(b':')
        key = key.lower()
        if not sep or key in headers: raise ValueError('invalid_headers')
        headers[key] = value.strip()
    if b'transfer-encoding' in headers: raise ValueError('unsupported_encoding')
    if b'content-length' in headers and (not headers[b'content-length'].isdigit() or int(headers[b'content-length']) != len(body)):
        raise ValueError('incomplete_response')
    return int(match[1]), headers, body


def root_response(code, content_type, body):
    if code != 404 or len(body) > 16384 or content_type.split(';', 1)[0].strip().lower() != 'application/json':
        return False
    try:
        data = json.loads(body)
        return isinstance(data, dict) and data.get('ok') is False and type(data.get('error_code')) is int and data['error_code'] == 404
    except (ValueError, UnicodeError):
        return False


def probe(host, port):
    code, headers, body = request(host, port, max_body=16384)
    return root_response(code, headers.get(b'content-type', b'').decode('ascii', errors='ignore'), body)
