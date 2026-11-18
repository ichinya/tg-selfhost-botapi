"""Allowlist projections. Input dictionaries and exception text are never public."""
import datetime as dt
import json
import math
import re
from pathlib import Path

MAX_STATUS_BYTES = 128 * 1024
MAX_INTEGER = (1 << 63) - 1
STATES = ['ready', 'unknown', 'unavailable', 'disabled', 'not_observed', 'stale', 'last_error_recorded']
REASONS = ['none', 'disabled', 'producer_not_configured', 'invalid', 'timeout', 'transport_error',
           'unexpected_response', 'closing', 'stale', 'permission_denied', 'not_observed',
           'ownership_required', 'migration_pause', 'instance_changed', 'unsupported']
STAGES = ['planned', 'preflight', 'source_switch', 'target_configuration', 'verification', 'finished', 'unknown']
OUTCOMES = ['pending', 'waiting', 'blocked', 'confirmed', 'partial', 'failed', 'reconciliation_required', 'unknown']
ALIAS = r'[A-Za-z0-9][A-Za-z0-9_-]{0,31}'


def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def count(value):
    if value is not None and (type(value) is not int or not 0 <= value <= MAX_INTEGER):
        raise ValueError('invalid_count')
    return value


def timestamp(value, now=None):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', value):
        raise ValueError('invalid_timestamp')
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    now = now or dt.datetime.now(dt.timezone.utc)
    if parsed > now + dt.timedelta(seconds=5):
        raise ValueError('future_timestamp')
    return parsed


def freshness(observed, now, ttl):
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (observed, now, ttl)):
        raise ValueError('invalid_clock')
    if now < observed or ttl < 0 or now - observed > MAX_INTEGER:
        raise ValueError('invalid_clock')
    return int(now - observed), now - observed <= ttl


def alias(value):
    if not isinstance(value, str) or not re.fullmatch(ALIAS, value, re.ASCII):
        raise ValueError('invalid_alias')
    return value


def object_schema(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


def string_enum(values):
    return dict(type='string', enum=values)


NUMBER = dict(type=['integer', 'null'], minimum=0, maximum=MAX_INTEGER)
TEXT = lambda pattern: dict(type=['string', 'null'], maxLength=256, pattern=pattern)
TIME = dict(type=['string', 'null'], format='date-time', maxLength=20)
LABEL = dict(type='string', pattern='^' + ALIAS + '$', maxLength=32)
ERROR = dict(type=['string', 'null'], enum=[None, 'timeout', 'tls', 'connect', 'http_4xx', 'http_5xx', 'unclassified_error'])
META = dict(source=string_enum(['process', 'manager', 'migration', 'webhook', 'runtime']),
            state=string_enum(STATES), reason=string_enum(REASONS), observed_at=TIME, age_seconds=NUMBER)
OPERATION = object_schema(dict(operation_id=dict(type='string', format='uuid', maxLength=36), alias=LABEL,
                              stage=string_enum(STAGES), outcome=string_enum(OUTCOMES), observed_at=TIME,
                              delivery_evidence=string_enum(['not_observed', 'confirmed'])))
BOT = object_schema(dict(alias=LABEL, state=string_enum(STATES), reason=string_enum(REASONS),
                         observed_at=TIME, age_seconds=NUMBER, mode=string_enum(['webhook', 'polling', 'unknown']),
                         pending_update_count=NUMBER, last_error_date=NUMBER, last_error_age_seconds=NUMBER,
                         last_error_category=ERROR, last_synchronization_error_date=NUMBER,
                         delivery_evidence=string_enum(['not_observed'])))
QUEUE = object_schema(dict(coverage=string_enum(['sampled', 'registered']), observed_clients=NUMBER,
                           known_pending_clients=NUMBER, pending_lower_bound=NUMBER))
DISK = object_schema(dict(role=string_enum(['work', 'temp']), filesystem=TEXT(r'^fs-[0-9a-f]{16}$'),
                          available_bytes=NUMBER, available_inodes=NUMBER))
DETAILS = dict(
    process=dict(depth=string_enum(['http_handler_only', 'http_handler_and_manager']), live=dict(type='boolean'), ready=dict(type='boolean')),
    migration=dict(operations=dict(type='array', items=OPERATION, maxItems=100)),
    webhook=dict(bots=dict(type='array', items=BOT, maxItems=100)),
    queue=dict(sampled=QUEUE, registered=QUEUE),
    storage=dict(filesystems=dict(type='array', items=DISK, maxItems=2)),
    image=dict(instance=TEXT(r'^[0-9a-f]{64}$'), binary_version=TEXT(r'^[0-9]+\.[0-9]+(?:\.[0-9]+)?$'),
               upstream_revision=TEXT(r'^[0-9a-f]{40}$'), build_key=TEXT(r'^[0-9a-f]{32}$'),
               image_id=TEXT(r'^sha256:[0-9a-f]{64}$'), registry_digest=TEXT(r'^sha256:[0-9a-f]{64}$'),
               platform=TEXT(r'^linux/(amd64|arm64)(/v[0-9]+)?$')))
SCHEMA = object_schema(dict(schema_version=dict(type='integer', const=1), **{
    name: object_schema(dict(META, **details)) for name, details in DETAILS.items()}))
for _name, _source in dict(process='process', migration='migration', webhook='webhook', queue='manager', storage='runtime', image='runtime').items():
    SCHEMA['properties'][_name]['properties']['source'] = string_enum([_source])
SCHEMA['$schema'] = 'https://json-schema.org/draft/2020-12/schema'


def validate(value, spec, now=None):
    """Validate the shipped JSON Schema subset without a third party dependency."""
    types = spec['type'] if isinstance(spec['type'], list) else [spec['type']]
    matches = {'null': value is None, 'integer': type(value) is int, 'boolean': type(value) is bool,
               'string': isinstance(value, str), 'array': isinstance(value, list), 'object': isinstance(value, dict)}
    if not any(matches[t] for t in types):
        raise ValueError('invalid_type')
    if 'const' in spec and value != spec['const'] or 'enum' in spec and value not in spec['enum']:
        raise ValueError('invalid_enum')
    if value is None:
        return None
    if type(value) is int and not spec.get('minimum', 0) <= value <= spec.get('maximum', MAX_INTEGER):
        raise ValueError('invalid_count')
    if isinstance(value, str):
        if len(value) > spec.get('maxLength', 256) or 'pattern' in spec and not re.fullmatch(spec['pattern'].strip('^$'), value, re.ASCII):
            raise ValueError('invalid_string')
        if spec.get('format') == 'date-time':
            timestamp(value, now)
        if spec.get('format') == 'uuid':
            import uuid
            if str(uuid.UUID(value)) != value:
                raise ValueError('invalid_uuid')
    if isinstance(value, list):
        if len(value) > spec.get('maxItems', 100):
            raise ValueError('too_many_items')
        return [validate(v, spec['items'], now) for v in value]
    if isinstance(value, dict):
        if set(value) != set(spec['required']):
            raise ValueError('invalid_fields')
        return {k: validate(value[k], s, now) for k, s in spec['properties'].items()}
    return value


def observation(source, state='unknown', reason='producer_not_configured', observed_at=None, age_seconds=None, **fields):
    result = dict(source=source, state=state, reason=reason, observed_at=observed_at, age_seconds=age_seconds, **fields)
    validate({k: result[k] for k in META}, object_schema(META))
    if (observed_at is None) != (age_seconds is None):
        raise ValueError('incomplete_freshness')
    return result


def empty_status(stats=False):
    q = lambda coverage: dict(coverage=coverage, observed_clients=None, known_pending_clients=None, pending_lower_bound=None)
    return dict(schema_version=1,
                process=observation('process', depth='http_handler_and_manager' if stats else 'http_handler_only', live=False, ready=False),
                migration=observation('migration', operations=[]), webhook=observation('webhook', 'disabled', 'disabled', bots=[]),
                queue=observation('manager', sampled=q('sampled'), registered=q('registered')),
                storage=observation('runtime', filesystems=[]),
                image=observation('runtime', **{k: None for k in DETAILS['image']}))


def serialize_status(value):
    safe = validate(value, SCHEMA)
    for name in DETAILS:
        section = safe[name]
        if (section['observed_at'] is None) != (section['age_seconds'] is None):
            raise ValueError('incomplete_freshness')
    result = json.dumps(safe, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('ascii')
    if len(result) > MAX_STATUS_BYTES:
        raise ValueError('status_too_large')
    return result


if __name__ == '__main__':
    Path(__file__).with_name('status.schema.json').write_text(json.dumps(SCHEMA, indent=2) + '\n', encoding='utf-8')
