"""Capture original compile evidence inside the build stage; no registry identity."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def link_inputs(root):
    commands, archives = [], {}
    final_found = False
    for link in sorted((root / 'build').rglob('link.txt')):
        command = link.read_text().strip()
        commands.append(f'### {link.relative_to(root)}\n{command}')
        cwd = link.parent.parent.parent
        tokens = shlex.split(command)
        # Archive creation commands describe outputs, not libraries consumed by
        # the server. Only the final executable link determines archive usage.
        final = any(token == '-o' and index + 1 < len(tokens)
                    and Path(tokens[index + 1]).name == 'telegram-bot-api'
                    for index, token in enumerate(tokens))
        if not final:
            continue
        final_found = True
        search = [Path('/usr/lib'), Path('/lib')]
        static = False
        for token in tokens:
            if token.startswith('-L'):
                search.insert(0, (cwd / token[2:]).resolve())
            elif token in ('-static', '-Wl,-Bstatic'):
                static = True
            elif token == '-Wl,-Bdynamic':
                static = False
            elif token.endswith('.a'):
                path = (cwd / token).resolve()
                if not path.is_file():
                    raise ValueError(f'Unresolved archive: {token}')
                archives[str(path)] = path
            elif token.startswith('-l'):
                resolved = False
                for directory in search:
                    shared, archive = directory / ('lib' + token[2:] + '.so'), directory / ('lib' + token[2:] + '.a')
                    if shared.exists() and not static:
                        resolved = True
                        break
                    if archive.exists():
                        archives[str(archive.resolve())] = archive.resolve()
                        resolved = True
                        break
                if not resolved:
                    # GCC also searches its versioned directories (for example libatomic).
                    candidates = ['lib' + token[2:] + suffix for suffix in (['.a'] if static else ['.so', '.a'])]
                    for candidate in candidates:
                        path = Path(output(tokens[0], '-print-file-name=' + candidate))
                        if path.is_absolute() and path.is_file():
                            if candidate.endswith('.a'):
                                archives[str(path.resolve())] = path.resolve()
                            resolved = True
                            break
                    if not resolved:
                        raise ValueError('Unresolved final-target link input: ' + token)
    if not final_found or not archives:
        raise ValueError('Missing final executable archive linkage')
    return commands, archives


def capture():
    evidence = Path('/usr/share/tg-selfhost-botapi/build')
    root = Path.cwd()
    binary = Path('/usr/local/bin/telegram-bot-api')
    commands, archives = link_inputs(root)
    records = []
    for name, path in sorted(archives.items()):
        if path.is_relative_to(root):
            owner = 'source:' + os.environ['BOT_API_REVISION']
        else:
            ownership = output('apk', 'info', '--who-owns', name)
            match = re.search(r' is owned by (\S+)', ownership)
            if not match:
                raise ValueError('Missing apk ownership: ' + name)
            owner = match[1]
        records.append({'path': name, 'sha256': sha(path), 'owner': owner})
    if not commands or not records:
        raise ValueError('Missing compile linkage evidence')
    (evidence / 'link-map.txt').write_bytes((root / 'build/telegram-bot-api.map').read_bytes())
    facts = {'compiler': output('c++', '--version'), 'cmake': output('cmake', '--version'),
             'linker': output('ld', '--version'), 'source_revision': output('git', 'rev-parse', 'HEAD'),
             'cmake_cache': (root / 'build/CMakeCache.txt').read_text()}
    if facts['source_revision'] != os.environ['BOT_API_REVISION']:
        raise ValueError('Actual source differs from resolved revision')
    (evidence / 'build-facts.json').write_text(json.dumps(facts, sort_keys=True, indent=2) + '\n')
    (evidence / 'binary.sha256').write_text(sha(binary) + '\n')
    (evidence / 'link-commands.txt').write_text('\n'.join(commands) + '\n')
    (evidence / 'dynamic.txt').write_text(output('readelf', '-d', str(binary)) + '\n')
    dynamic_owners = []
    for line in output('ldd', str(binary)).splitlines():
        paths = re.findall(r'(?:=>\s+|^\s*)(/[^\s()]+)', line)
        for name in paths:
            path = Path(name).resolve()
            ownership = output('apk', 'info', '--who-owns', str(path))
            match = re.search(r' is owned by (\S+)', ownership)
            if not match:
                raise ValueError('Missing dynamic library ownership: ' + name)
            dynamic_owners.append({'path': str(path), 'sha256': sha(path), 'owner': match[1]})
    if not dynamic_owners:
        raise ValueError('Missing dynamic library ownership')
    (evidence / 'dynamic-owners.json').write_text(json.dumps(dynamic_owners, sort_keys=True, indent=2) + '\n')
    (evidence / 'static-archives.txt').write_text(json.dumps(records, sort_keys=True, indent=2) + '\n')
    inputs = {key: os.environ[key] for key in ('BOT_API_REVISION', 'ALPINE_IMAGE', 'BUILD_FINGERPRINT', 'APK_REFRESH_ID', 'TARGETPLATFORM')}
    record = {'schema': 1, 'inputs': inputs, 'binary_sha256': sha(binary),
              'source_submodules': output('git', 'submodule', 'status', '--recursive'),
              'hashes': {p.name: sha(p) for p in sorted(evidence.iterdir()) if p.is_file()}}
    (evidence / 'compile-receipt.json').write_text(json.dumps(record, sort_keys=True, indent=2) + '\n')


if __name__ == '__main__':
    capture()
