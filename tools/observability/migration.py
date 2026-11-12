"""Read only dedicated sanitized projections, never private migration dossiers."""
import datetime as dt
import json
import os
from pathlib import Path
import stat
from . import schema


def read_json(path, private=False, limit=65536):
    path = Path(path).absolute()
    # Reject symlinks in every component; on POSIX also open each directory with
    # O_NOFOLLOW so a concurrent rename cannot redirect the reader.
    for part in [path, *path.parents]:
        if part.is_symlink(): raise ValueError('unsafe_input')
    directory = None
    fd = None
    try:
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        if os.name == 'posix':
            directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
            for part in path.parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory); directory = child
            fd = os.open(path.name, flags, dir_fd=directory)
        else:
            fd = os.open(path, flags)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('unsafe_input')
        if private and (os.name != 'posix' or info.st_mode & 0o077 or info.st_uid != os.getuid()):
            raise ValueError('private_permissions')
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            body = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        if len(body) > limit or (info.st_ino, info.st_size, info.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('input_changed')
        return json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid_number')),
                          object_pairs_hook=unique_fields)
    finally:
        if fd is not None: os.close(fd)
        if directory is not None: os.close(directory)


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('duplicate_field')
        result[key] = value
    return result


PROJECTION = schema.object_schema(dict(schema_version=dict(type='integer', const=1),
    observed_at=schema.TIME, operations=dict(type='array', maxItems=100, items=schema.OPERATION)))


def read_migrations(directory=None, now=None):
    if not directory: return schema.observation('migration', operations=[])
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        data = schema.validate(read_json(Path(directory) / 'status.json'), PROJECTION, now)
        if data['observed_at'] is None: raise ValueError('missing_time')
        age = max(0, int((now - schema.timestamp(data['observed_at'], now)).total_seconds()))
        seen = set()
        for op in data['operations']:
            if op['operation_id'] in seen or op['observed_at'] is None: raise ValueError('invalid_operation')
            seen.add(op['operation_id'])
            if schema.timestamp(op['observed_at'], now) > schema.timestamp(data['observed_at'], now): raise ValueError('invalid_time')
        # Historical terminal observations remain visible but never become fresh.
        return schema.observation('migration', 'stale' if age > 180 else 'ready', 'stale' if age > 180 else 'none',
                                  data['observed_at'], age, operations=data['operations'])
    except (OSError, ValueError, UnicodeError, OverflowError):
        return schema.observation('migration', 'unavailable', 'invalid', operations=[])


def permits_polling(migration, allow_unobserved=False):
    if migration['reason'] == 'producer_not_configured': return allow_unobserved is True
    return (migration['state'] == 'ready' and bool(migration['operations']) and
            all(op['stage'] == 'finished' and op['outcome'] == 'confirmed' for op in migration['operations']))
