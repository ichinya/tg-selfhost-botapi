"""Trusted host CLI: targeted read-only Docker observations, no HTTP listener."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from observability import schema
from observability.runtime import RUNTIME


def run(argv):
    """Bound time and combined output; never return exception text."""
    output = bytearray()
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
        def read():
            while True:
                part = process.stdout.read(4096)
                if not part: break
                output.extend(part)
                if len(output) > 65536:
                    process.kill(); break
        thread = threading.Thread(target=read, daemon=True); thread.start()
        try: code = process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(); raise ValueError('runtime_unavailable') from None
        thread.join(timeout=1)
        if code or thread.is_alive() or len(output) > 65536: raise ValueError('runtime_unavailable')
    return bytes(output).decode('utf-8').strip()


def identity(container):
    state = container.get('State', {})
    if not state.get('Running') or any(state.get(k) for k in ['Paused', 'Restarting', 'Dead']): raise ValueError('container_unavailable')
    values = (container.get('Id'), state.get('StartedAt'), container.get('Image'), state.get('Pid'))
    if not all(values): raise ValueError('invalid_identity')
    return values


def safe_value(value, pattern):
    return value if isinstance(value, str) and re.fullmatch(pattern, value) else None


def exec_command(cid, *args, user=None):
    return ['docker', 'exec', *(['--user', user] if user else []), cid,
            'timeout', '-s', 'TERM', '5', *args]


def collect(compose, service='botapi', runner=run):
    ids = runner([*compose, 'ps', '-q', service]).splitlines()
    if len(ids) != 1 or not re.fullmatch(r'[0-9a-f]{12,64}', ids[0]): raise ValueError('ambiguous_target')
    cid = ids[0]
    inspect = lambda: json.loads(runner(['docker', 'inspect', '--format', '{{json .}}', cid]))
    before = inspect(); generation = identity(before)
    image = json.loads(runner(['docker', 'image', 'inspect', '--format', '{{json .}}', before['Image']]))
    if image.get('Id') != before['Image']: raise ValueError('image_mismatch')
    labels = image.get('Config', {}).get('Labels') or {}
    if labels.get('org.opencontainers.image.source') != 'https://github.com/ichinya/tg-selfhost-botapi':
        raise ValueError('unsupported_image')
    argv = runner(exec_command(cid, 'cat', '/proc/1/cmdline')).split('\x00')
    if not argv or argv[0].rsplit('/', 1)[-1] != 'telegram-bot-api': raise ValueError('unsupported_process')
    from doctor_checks import process_flags
    flags = process_flags([v for v in argv[1:] if v])
    paths = [flags.get('dir'), flags.get('temp-dir')]
    if any(not isinstance(p, str) or not p.startswith('/') or '\x00' in p or '\n' in p for p in paths):
        raise ValueError('unknown_paths')
    # Use the server's observed effective identity for filesystem metadata.
    status = runner(exec_command(cid, 'cat', '/proc/1/status'))
    uid = re.search(r'^Uid:\s+\d+\s+(\d+)', status, re.M)
    gid = re.search(r'^Gid:\s+\d+\s+(\d+)', status, re.M)
    if not uid or not gid: raise ValueError('identity_unavailable')
    disks = []
    for role, path in zip(['work', 'temp'], paths):
        fields = runner(exec_command(cid, 'stat', '-f', '-c', '%i %a %S', '--', path, user=uid[1] + ':' + gid[1])).split()
        if len(fields) != 3 or not re.fullmatch(r'[0-9a-fA-F]+', fields[0]) or not all(v.isdecimal() for v in fields[1:]):
            raise ValueError('invalid_filesystem')
        disks.append(dict(role=role, filesystem='fs-' + hashlib.sha256(fields[0].encode()).hexdigest()[:16],
                          available_bytes=schema.count(int(fields[1]) * int(fields[2])), available_inodes=None))
    version = runner(exec_command(cid, 'telegram-bot-api', '--version', user=uid[1] + ':' + gid[1]))
    match = re.fullmatch(r'(?:(?:Telegram )?Bot API(?: server)?\s+)?([0-9]+\.[0-9]+(?:\.[0-9]+)?)(?:\s+\(.*\))?', version)
    digests = [d.rsplit('@', 1)[-1] for d in image.get('RepoDigests') or [] if isinstance(d, str)]
    digest = next((safe_value(d, r'sha256:[0-9a-f]{64}') for d in digests if safe_value(d, r'sha256:[0-9a-f]{64}')), None)
    public = dict(instance=hashlib.sha256(json.dumps(generation[:3], separators=(',', ':')).encode()).hexdigest(),
        binary_version=match[1] if match else None,
        upstream_revision=safe_value(labels.get('io.tg-selfhost.bot-api-revision'), r'[0-9a-f]{40}'),
        build_key=safe_value(labels.get('io.tg-selfhost.build-key'), r'[0-9a-f]{32}'),
        image_id=safe_value(before['Image'], r'sha256:[0-9a-f]{64}'), registry_digest=digest,
        platform=safe_value(str(image.get('Os')) + '/' + str(image.get('Architecture')), r'linux/(amd64|arm64)'))
    if identity(inspect()) != generation: raise ValueError('instance_changed')
    return schema.validate(dict(schema_version=1, observed_at=schema.utcnow(), image=public, storage=dict(filesystems=disks)), RUNTIME)


def atomic_write(directory, value):
    directory = Path(directory).absolute()
    if not directory.is_dir() or any(p.is_symlink() for p in [directory, *directory.parents]): raise ValueError('unsafe_output')
    info = directory.stat()
    if os.name == 'posix' and (info.st_uid != os.getuid() or info.st_mode & 0o022): raise ValueError('unsafe_output')
    target = directory / 'status.json'
    if target.is_symlink(): raise ValueError('unsafe_output')
    content = json.dumps(schema.validate(value, RUNTIME), separators=(',', ':'), allow_nan=False).encode('ascii')
    if len(content) > 65536: raise ValueError('output_limit')
    import uuid
    name = directory / ('.status-' + uuid.uuid4().hex)
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        os.chmod(name, 0o644)
        os.replace(name, target)
    finally:
        if os.path.exists(name): os.unlink(name)


def main():
    class SafeParser(argparse.ArgumentParser):
        def error(self, message): raise ValueError('invalid_arguments')
    parser = SafeParser(description=__doc__)
    parser.add_argument('--project-directory', required=True)
    parser.add_argument('--file', action='append', required=True)
    parser.add_argument('--project-name')
    parser.add_argument('--service', default='botapi', choices=['botapi'])
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    project = Path(args.project_directory).resolve(strict=True)
    output = project / '.observability/runtime'
    command = ['docker', 'compose', '--project-directory', str(project)]
    if args.project_name: command += ['--project-name', args.project_name]
    for file in args.file: command += ['-f', str((project / file).resolve(strict=True))]
    while True:
        try: atomic_write(output, collect(command, args.service))
        except Exception:
            print('runtime_observation_unavailable', file=sys.stderr)
            if not args.watch: return 1
        if not args.watch: return 0
        time.sleep(30)


if __name__ == '__main__':
    try: code = main()
    except Exception:
        print('runtime_observation_unavailable', file=sys.stderr); code = 1
    raise SystemExit(code)
