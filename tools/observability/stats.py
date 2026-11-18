"""Numeric projection of the reviewed tab-separated manager response."""
import re
from .schema import MAX_INTEGER

HEADER = b'DURATION\tinf\t5sec\t1min\t1hour'
# Upstream's StringBuilder is 16 KiB. A full buffer can be a truncated response.
MAX_BODY = 16383
COUNTERS = {'bot_count', 'active_bot_count', 'active_webhook_connections', 'active_requests', 'active_network_queries'}


def integer(value):
    if not re.fullmatch(rb'[0-9]{1,19}', value) or int(value) > MAX_INTEGER:
        raise ValueError('invalid_counter')
    return int(value)


def parse(body):
    if type(body) is not bytes or len(body) >= MAX_BODY or not body.endswith(b'\n'):
        raise ValueError('invalid_stats')
    lines = body.splitlines()
    if any(b'Closing' in line for line in lines): raise ValueError('closing')
    if not lines or lines[0] != HEADER or len(lines) > 4096:
        raise ValueError('invalid_stats')
    counters, blocks, client = {}, [], None
    for line in lines[1:]:
        if not line:
            if client == {}:
                raise ValueError('invalid_block')
            client = {}; blocks.append(client)
            if len(blocks) > 50:
                raise ValueError('client_limit')
            continue
        fields = line.split(b'\t')
        if not 2 <= len(fields) <= 8 or not fields[0] or len(line) > 4096:
            raise ValueError('invalid_line')
        key, value = fields[:2]
        if client is None:
            if key == b'uptime':
                if 'uptime' in counters or len(fields) != 2 or not re.fullmatch(rb'[0-9]{1,19}(?:\.[0-9]{1,9})?', value) or float(value) > MAX_INTEGER:
                    raise ValueError('invalid_uptime')
                counters['uptime'] = float(value)
            elif key.decode('ascii', errors='ignore') in COUNTERS:
                name = key.decode('ascii')
                if name in counters or len(fields) != 2:
                    raise ValueError('duplicate_counter')
                counters[name] = integer(value)
        elif key in {b'id', b'uptime', b'token', b'username', b'head_update_id', b'pending_update_count'}:
            if key in client or len(fields) != 2:
                raise ValueError('duplicate_field')
            client[key] = integer(value) if key == b'pending_update_count' else True
    if not {'uptime', 'bot_count', 'active_bot_count'} <= counters.keys():
        raise ValueError('missing_counter')
    required = {b'id', b'uptime', b'token', b'username', b'head_update_id'}
    if any(not required <= block.keys() for block in blocks):
        raise ValueError('incomplete_client')
    counts = [block[b'pending_update_count'] for block in blocks if b'pending_update_count' in block]
    total = sum(counts) if counts else None
    if total is not None and total > MAX_INTEGER:
        raise ValueError('overflow')
    return dict(counters=counters, queue=dict(coverage='sampled', observed_clients=len(blocks),
                known_pending_clients=len(counts), pending_lower_bound=total))


def fetch():
    from .probes import request
    code, headers, body = request('127.0.0.1', 8082)
    if code != 200:
        raise ValueError('unexpected_response')
    return parse(body)
