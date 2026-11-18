"""Read sanitized host observations. This module never invokes Docker."""
import datetime as dt
from pathlib import Path
from . import schema
from .migration import read_json

RUNTIME = schema.object_schema(dict(schema_version=dict(type='integer', const=1), observed_at=schema.TIME,
    image=schema.object_schema(schema.DETAILS['image']),
    storage=schema.object_schema(dict(filesystems=dict(type='array', items=schema.DISK, maxItems=2)))))


def read_runtime(directory=None, now=None):
    empty = schema.empty_status()
    if not directory: return empty['storage'], empty['image']
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        data = schema.validate(read_json(Path(directory) / 'status.json'), RUNTIME, now)
        roles = [item['role'] for item in data['storage']['filesystems']]
        if len(roles) != len(set(roles)): raise ValueError('duplicate_role')
        if data['observed_at'] is None or data['image']['instance'] is None: raise ValueError('invalid_runtime')
        age = max(0, int((now - schema.timestamp(data['observed_at'], now)).total_seconds()))
        state, reason = ('stale', 'stale') if age > 90 else ('ready', 'none')
        return (schema.observation('runtime', state, reason, data['observed_at'], age, **data['storage']),
                schema.observation('runtime', state, reason, data['observed_at'], age, **data['image']))
    except (OSError, ValueError, UnicodeError, OverflowError):
        return (schema.observation('runtime', 'unavailable', 'invalid', filesystems=[]),
                schema.observation('runtime', 'unavailable', 'invalid', **{k: None for k in schema.DETAILS['image']}))
