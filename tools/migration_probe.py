"""Fresh token-free readiness and explicit private deployment evidence."""
import json
import os
from pathlib import Path, PurePosixPath
import stat
import time
from migration_contract import normalize_endpoint, fingerprint, canonical, decode_json


def private_json(path):
    path=Path(path)
    if os.name!='posix':
        raise ValueError('private evidence requires POSIX')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    with os.fdopen(fd,'rb') as f:
        info=os.fstat(f.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink!=1):
            raise ValueError('evidence file must be private')
        raw=f.read(262145)
    if len(raw)>262144:
        raise ValueError('evidence too large')
    from migration_store import _unique_object, _reject_constant
    return json.loads(raw,object_pairs_hook=_unique_object,parse_constant=_reject_constant)


def protocol_ok(result):
    if result.status!=404 or result.content_type.split(';',1)[0].strip().lower()!='application/json':
        return False
    try:
        p=decode_json(result.body)
    except (ValueError,UnicodeError,RecursionError):
        return False
    return isinstance(p,dict) and p.get('ok') is False and type(p.get('error_code')) is int and p['error_code']==404


def validate_evidence(record, endpoint, *, now=None):
    fields={'version','endpoint','created_at','deployment_id','provenance','image_id','image_digest',
            'config_digest','credentials_configured','persistent_path','temp_path','persistent_mount_id',
            'temp_mount_id','runtime_uid','runtime_gid','write_verified','local_forbidden_roots'}
    if not isinstance(record,dict) or set(record) - {'local_mode'} != fields or type(record['version']) is not int or record['version']!=1:
        raise ValueError('incomplete deployment evidence')
    if normalize_endpoint(record['endpoint'])!=normalize_endpoint(endpoint):
        raise ValueError('evidence endpoint mismatch')
    now=time.time() if now is None else now
    if type(record['created_at']) not in (int,float) or not 0 <= now-record['created_at'] <= 300:
        raise ValueError('stale deployment evidence')
    import re
    for n in ('image_id','image_digest','config_digest'):
        if n == 'image_digest' and record[n] is None:
            continue  # local-build image ID remains mandatory
        if not isinstance(record[n],str) or not re.fullmatch(r'(sha256:)?[0-9a-f]{64}',record[n]):
            raise ValueError('invalid image or config identity')
    for n in ('deployment_id','provenance','persistent_mount_id'):
        if not isinstance(record[n],str) or not record[n] or len(record[n])>1024:
            raise ValueError('missing evidence provenance')
    if record['credentials_configured'] is not True or record['write_verified'] is not True:
        raise ValueError('deployment not writable or configured')
    if not isinstance(record['local_forbidden_roots'],list) or any(not isinstance(p,str) or not Path(p).is_absolute() for p in record['local_forbidden_roots']):
        raise ValueError('explicit local mount/webroot exclusions required')
    for n in ('runtime_uid','runtime_gid'):
        if type(record[n]) is not int or record[n]<0:
            raise ValueError('runtime identity required')
    a,b=PurePosixPath(record['persistent_path']),PurePosixPath(record['temp_path'])
    if (not a.is_absolute() or not b.is_absolute() or a==b or a in b.parents or b in a.parents
            or any(part in ('.','..') for path in (record['persistent_path'],record['temp_path']) for part in path.split('/'))):
        raise ValueError('separate persistent and temporary paths required')
    if 'local_mode' in record and type(record['local_mode']) is not bool:
        raise ValueError('explicit deployment mode required')
    return record


class Readiness:
    def __init__(self,client,evidence_provider,key,*,state_root=None):
        self.client=client
        self.evidence_provider=evidence_provider
        self.key=key
        self.state_root=Path(state_root).resolve() if state_root else None
        self.local_mode = None

    def check(self,endpoint):
        # A new network observation is mandatory even with a fresh record.
        result=self.client.request(endpoint)
        if not protocol_ok(result):
            raise ValueError('token-free target probe failed')
        record=validate_evidence(self.evidence_provider(),endpoint)
        self.local_mode = record.get('local_mode')
        self.record = record
        if self.state_root:
            for root in record['local_forbidden_roots']:
                forbidden=Path(root).resolve()
                if self.state_root==forbidden or forbidden in self.state_root.parents:
                    raise ValueError('journal overlaps a deployment mount or webroot')
        stable={k:v for k,v in record.items() if k not in ('created_at','provenance')}
        stable['endpoint']=normalize_endpoint(stable['endpoint'])
        stable['local_forbidden_roots']=sorted(stable['local_forbidden_roots'])
        return fingerprint(self.key,canonical(stable))


class CloudReadiness:
    """Public cloud has no operator-managed image/mount/credential evidence."""
    local_mode = False
    def __init__(self, client, key):
        self.client, self.key = client, key

    def check(self, endpoint):
        if normalize_endpoint(endpoint) != 'https://api.telegram.org' or not protocol_ok(self.client.request(endpoint)):
            raise ValueError('official cloud protocol probe failed')
        return fingerprint(self.key, canonical({'role':'official_cloud','endpoint':'https://api.telegram.org','local_mode':False}))


class DockerEvidence:
    """Explicitly selected managed container; no credential values are returned.

    This adapter inspects a running target and creates/removes its own tiny
    write probes as the actual account used by this repository's entrypoint.
    It does not start, stop or reconfigure containers.
    """
    def __init__(self, container, endpoint, expected_image, key):
        import re
        if not re.fullmatch('[a-zA-Z0-9_.-]{1,128}',container):
            raise ValueError('invalid container reference')
        self.container,self.endpoint,self.expected_image,self.key=container,endpoint,expected_image,key

    @staticmethod
    def run(*args):
        import subprocess
        try:
            result=subprocess.run(['docker',*args],capture_output=True,timeout=20,check=False)
        except (OSError,subprocess.SubprocessError):
            raise ValueError('managed deployment inspection failed') from None
        if result.returncode:
            raise ValueError('managed deployment inspection failed')
        return result.stdout.decode('utf-8')

    def __call__(self):
        import hashlib
        info=json.loads(self.run('inspect',self.container))[0]
        if info['Image']!=self.expected_image or not info['State']['Running']:
            raise ValueError('managed image identity or readiness mismatch')
        env=dict(v.split('=',1) for v in info['Config']['Env'] if '=' in v)
        if not all(env.get(k) or env.get(k+'_FILE') for k in ('TELEGRAM_API_ID','TELEGRAM_API_HASH')):
            raise ValueError('managed application credentials not configured')
        for name in ('TELEGRAM_API_ID', 'TELEGRAM_API_HASH'):
            if env.get(name) and env.get(name+'_FILE'):
                raise ValueError('managed credential input is ambiguous')
        # Read credentials only inside the selected container; stdout is empty.
        credentials = '''set -eu
v=${TELEGRAM_API_ID:-}; [ -z "${TELEGRAM_API_ID_FILE:-}" ] || v=$(cat "$TELEGRAM_API_ID_FILE")
case "$v" in ''|*[!0-9]*) exit 1;; esac
[ "$v" -gt 0 ] && [ "$v" -le 2147483647 ]
h=${TELEGRAM_API_HASH:-}; [ -z "${TELEGRAM_API_HASH_FILE:-}" ] || h=$(cat "$TELEGRAM_API_HASH_FILE")
[ "${#h}" -eq 32 ]; case "$h" in *[!0-9a-fA-F]*) exit 1;; esac
'''
        self.run('exec',self.container,'sh','-c',credentials)
        work,temp=env.get('TELEGRAM_WORK_DIR','/var/lib/telegram-bot-api'),env.get('TELEGRAM_TEMP_DIR','/tmp/telegram-bot-api')
        mounts={m['Destination']:m for m in info['Mounts']}
        if work not in mounts or not mounts[work]['RW'] or temp in mounts and not mounts[temp]['RW']:
            raise ValueError('managed persistent mount must be writable')
        uid=int(self.run('exec',self.container,'id','-u','telegram-bot-api').strip())
        gid=int(self.run('exec',self.container,'id','-g','telegram-bot-api').strip())
        script='set -eu; a=$(mktemp "$1/.migration-write.XXXXXX"); trap \'rm -f "$a"\' EXIT; printf fixture > "$a"; test -r "$a"'
        for directory in (work,temp):
            self.run('exec','--user',f'{uid}:{gid}',self.container,'sh','-c',script,'sh',directory)
        image=json.loads(self.run('image','inspect',self.expected_image))[0]
        digests=image.get('RepoDigests',[])
        return dict(version=1,endpoint=self.endpoint,created_at=time.time(),deployment_id=info['Id'],
                    provenance='docker_inspect_and_runtime_write_probe',image_id=info['Image'],
                    image_digest=digests[0].split('@')[-1] if digests else None,config_digest=fingerprint(self.key,canonical(info['Config'])),
                    credentials_configured=True,persistent_path=work,temp_path=temp,
                    persistent_mount_id=mounts[work].get('Name',mounts[work]['Source']),
                    temp_mount_id=mounts[temp].get('Name',mounts[temp]['Source']) if temp in mounts else None,
                    local_forbidden_roots=[m['Source'] for m in info['Mounts']],
                    local_mode=env.get('TELEGRAM_LOCAL','0').lower() in ('1','true','yes'),
                    runtime_uid=uid,runtime_gid=gid,write_verified=True)


def validate_webhook_mode(profile, local_mode):
    """Mode is deployment evidence; endpoint hostname never implies it."""
    from migration_contract import validate_profile
    from urllib.parse import urlsplit
    import ipaddress
    validate_profile(profile, 'polling' if profile.get('mode') == 'polling' else 'set')
    if profile['mode'] == 'polling' or local_mode is True:
        return
    if local_mode is not False:
        raise ValueError('deployment mode has not been verified')
    url = urlsplit(profile['url'])
    if url.scheme != 'https' or (url.port or 443) not in (80, 88, 443, 8443):
        raise ValueError('cloud webhook protocol or port rejected')
    for host in (url.hostname, profile.get('ip_address')):
        if host is None:
            continue
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            continue  # Bot API validates DNS at registration; no webhook HEAD.
        if address.version != 4 or not address.is_global:
            raise ValueError('cloud webhook address rejected')
    if profile.get('max_connections', 40) > 100:
        raise ValueError('cloud webhook connection limit rejected')
