"""PR42 cold-backup validation primitives; no deployment authority."""
import hashlib, io, tarfile
from pathlib import Path

def archive_manifest(raw):
    """Private content/owner/mode comparison; only the aggregate hash is public."""
    result = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive.getmembers():
            if member.name.startswith('/') or '..' in Path(member.name).parts or member.name in result:
                raise ValueError('Unsafe or duplicate archive entry')
            if not (member.isfile() or member.isdir()):
                raise ValueError('Links and special files are not permitted in a cold backup')
            contents = archive.extractfile(member).read() if member.isfile() else b''
            result[member.name] = (member.type.decode('ascii'), member.uid, member.gid, member.mode,
                                   member.size, member.linkname, hashlib.sha256(contents).hexdigest())
    return result

def validate_shutdown(events, state):
    """A zero exit alone cannot establish the cold-backup precondition."""
    signals = [str(e.get('Actor', {}).get('Attributes', {}).get('signal'))
               for e in events if e.get('Action') == 'kill']
    exited = [e for e in events if e.get('Action') == 'die'
              and str(e.get('Actor', {}).get('Attributes', {}).get('exitCode')) == '0']
    if (state.get('Running') or state.get('OOMKilled') or state.get('ExitCode') != 0
            or any(e.get('Action') == 'oom' for e in events)
            or signals not in (['15'], ['SIGTERM']) or len(exited) != 1):
        raise ValueError('Unclean or unobserved shutdown; backup aborted')
