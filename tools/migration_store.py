"""Private, single-host POSIX storage primitives for migration state.

This module does not implement the migration protocol.  Callers must validate
the schema and persist an intent before sending any remote mutation.
"""

import contextlib
try:
    import fcntl
except ImportError:
    fcntl = None
import json
import os
from pathlib import Path
import re
import stat
import secrets


class StateError(Exception):
    """State storage is unavailable, unsafe, or already in use."""


def _private_directory(path, forbidden=()):
    if os.name != 'posix' or fcntl is None:
        raise StateError('POSIX private filesystem required; use Linux or WSL')
    if not Path(path).is_absolute():
        raise StateError("state root must be absolute")
    path = Path(os.path.abspath(path))
    checkout = Path(__file__).resolve().parent.parent
    standard_webroots = (Path('/var/www'),Path('/srv/www'),Path('/usr/share/nginx/html'))
    for item in (checkout, *standard_webroots, *map(lambda p: Path(os.path.abspath(p)), forbidden)):
        if path == item or item in path.parents:
            raise StateError("state root must be outside checkout and Bot API data")
    # Resolve each component without following symbolic links.  This also
    # rejects symlinked parents, not just a symlink at the final component.
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise StateError("state path contains a symbolic link")
        if current.exists() and current != path:
            info = current.stat()
            if info.st_uid not in (0, os.geteuid()) or (info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX)):
                raise StateError('untrusted state ancestor')
    try:
        path.mkdir(mode=0o700, parents=False, exist_ok=True)
        info = path.stat()
    except OSError as exc:
        raise StateError("cannot access state directory") from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise StateError("state directory must be owned by the current user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise StateError("state directory must be private (mode 0700)")
    return path


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise StateError("invalid state identifier")
    return value


def _open_private(path, flags, dir_fd=None):
    try:
        fd = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dir_fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077 or info.st_nlink != 1:
            os.close(fd)
            raise StateError("state file is not private")
        return fd
    except OSError as exc:
        raise StateError("cannot open private state file") from exc


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate state key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("invalid JSON constant")


class StateStore:
    def __init__(self, root=None, *, data_dirs=(), create=True):
        if os.name!='posix' or fcntl is None:
            raise StateError('POSIX private filesystem required; use Linux or WSL')
        if root is None:
            root = os.environ.get("MIGRATION_STATE_DIR")
            if root is None:
                base = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local' / 'state')))
                root = base / 'tg-selfhost-botapi' / 'migrations'
                for parent in reversed(root.parents) if create else ():
                    if not parent.exists():
                        parent.mkdir(mode=0o700)
        if not create and not Path(root).is_dir():
            raise StateError('saved state root missing')
        self.root = _private_directory(root, data_dirs)
        self._dirfd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(self._dirfd)
        self._identity = (info.st_dev, info.st_ino)
        self._check_root()
        # POSIX-shaped network/Windows mounts do not establish these guarantees.
        try:
            mounts = []
            for line in Path('/proc/self/mountinfo').read_text().splitlines():
                before, after = line.split(' - ',1)
                mount = Path(before.split()[4].replace('\\040',' '))
                if self.root == mount or mount in self.root.parents:
                    mounts.append((len(str(mount)),after.split()[0]))
            filesystem = max(mounts)[1]
            if filesystem not in ('ext4','xfs','btrfs','tmpfs','overlay','zfs'):
                raise StateError('unverified state filesystem')
        except (OSError,ValueError,IndexError):
            raise StateError('cannot establish state filesystem guarantees') from None

    def __del__(self):
        if hasattr(self, "_dirfd"):
            os.close(self._dirfd)

    def _check_root(self):
        try:
            if self.root.resolve() != self.root:
                raise StateError('state ancestor was replaced by a symlink')
            info = os.stat(self.root, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != self._identity:
                raise StateError("state directory was replaced")
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise StateError("state directory is not private")
        except OSError as exc:
            raise StateError("state directory unavailable") from exc

    def binding_key(self, create=True):
        """Load or create the private HMAC key with durable directory entry."""
        self._check_root()
        if create and not (self.root / 'binding.key').exists() and any(self.root.glob('*.json')):
            raise StateError('binding key lost; restore the journal and key together')
        if not create:
            fd = _open_private('binding.key',os.O_RDONLY,self._dirfd)
            with os.fdopen(fd,'rb') as stream:
                key=stream.read(33)
            if len(key)!=32:
                raise StateError('invalid binding key')
            return key
        try:
            fd = _open_private("binding.key", os.O_WRONLY | os.O_CREAT | os.O_EXCL, self._dirfd)
        except StateError as exc:
            if not isinstance(exc.__cause__, FileExistsError):
                raise
            fd = _open_private("binding.key", os.O_RDONLY, self._dirfd)
            with os.fdopen(fd, "rb") as stream:
                key = stream.read(33)
            if len(key) != 32:
                raise StateError("invalid binding key")
            return key
        try:
            key = secrets.token_bytes(32)
            with os.fdopen(fd, "wb") as stream:
                stream.write(key)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(self._dirfd)
            return key
        except OSError as exc:
            raise StateError("cannot durably write binding key") from exc

    @contextlib.contextmanager
    def lock(self, bot_id):
        """Hold the per-bot lock until the context and all inheriting workers end."""
        key = _name(str(bot_id))
        self._check_root()
        fd = _open_private("bot-" + key + ".lock", os.O_RDWR | os.O_CREAT, self._dirfd)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise StateError("bot state is already locked") from exc
            # Subprocesses must explicitly use pass_fds=(fd,) so that a
            # supervisor death cannot release a live worker's lock.
            yield fd
        finally:
            os.close(fd)

    def read(self, operation_id):
        self._check_root()
        path = _name(operation_id) + ".json"
        fd = _open_private(path, os.O_RDONLY, self._dirfd)
        try:
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                raw = stream.read(4194305)
                if len(raw) > 4194304:
                    raise ValueError('state snapshot too large')
                snapshot = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
                if not isinstance(snapshot, dict):
                    raise ValueError("state snapshot must be an object")
                return snapshot
        except (ValueError, UnicodeError, OSError) as exc:
            raise StateError("invalid state snapshot") from exc

    def write(self, operation_id, snapshot):
        """Atomically replace a snapshot and sync both file and directory."""
        self._check_root()
        path = _name(operation_id) + ".json"
        if not isinstance(snapshot, dict):
            raise StateError("state snapshot must be an object")
        try:
            data = json.dumps(snapshot, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii") + b"\n"
        except (TypeError, ValueError) as exc:
            raise StateError("state snapshot is not serializable") from exc
        temporary = None
        try:
            temporary = ".snapshot-" + secrets.token_hex(16)
            fd = _open_private(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, self._dirfd)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self._check_root()
            os.replace(temporary, path, src_dir_fd=self._dirfd, dst_dir_fd=self._dirfd)
            temporary = None
            os.fsync(self._dirfd)
        except OSError as exc:
            raise StateError("cannot durably write state snapshot") from exc
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary, dir_fd=self._dirfd)
                except FileNotFoundError:
                    pass

    def close(self):
        if hasattr(self, '_dirfd'):
            os.close(self._dirfd)
            del self._dirfd


# The journal is a signed, closed-schema envelope. No runtime values or raw
# HTTP responses are admitted; references and commitments are sufficient.
import copy
import hashlib
import hmac
import time
from migration_contract import (SCHEMA_VERSION, canonical, fingerprint,
                                plan_digest, validate_plan)


def sids(state):
    return tuple(step['id'] for step in state['plan']['steps'])


def _validate_state(s):
    if not isinstance(s, dict) or set(s) != {'schema_version','plan','digest','steps','checkpoints','results','snapshot','deployment'}:
        raise StateError('invalid journal schema')
    if type(s['schema_version']) is not int or s['schema_version'] != SCHEMA_VERSION:
        raise StateError('unsupported journal version')
    validate_plan(s['plan'])
    if s['digest'] != plan_digest(s['plan']) or set(s['steps']) != {step['id'] for step in s['plan']['steps']}:
        raise StateError('invalid journal binding')
    if set(s['checkpoints']) - {'confirmed','quiescence','endpoint_change','application_start','target_verified','delivery','superseded','state_transfer'}:
        raise StateError('invalid checkpoint')
    for value in s['checkpoints'].values():
        if (not isinstance(value,dict) or set(value)!={'commitment','time'}
                or not isinstance(value['commitment'],str) or not re.fullmatch('[0-9a-f]{64}',value['commitment'])
                or type(value['time']) not in (int,float) or not 0 <= value['time'] <= 1e12):
            raise StateError('invalid checkpoint receipt')
    if s['snapshot'] is not None and not re.fullmatch('[0-9a-f]{64}', s['snapshot']):
        raise StateError('invalid source snapshot')
    if s['deployment'] is not None and (not isinstance(s['deployment'],str) or not re.fullmatch('[0-9a-f]{64}',s['deployment'])):
        raise StateError('invalid deployment binding')
    if set(s['results']) != {'service_readiness','migration_outcome','webhook_configuration','delivery_verification'}:
        raise StateError('invalid result fields')
    for value in s['results'].values():
        if value not in ('pending','confirmed','failed','unknown','blocked','partial','NOTRUN','mock','live'):
            raise StateError('invalid result')
    seen = set()
    for attempts in s['steps'].values():
        if not isinstance(attempts, list):
            raise StateError('invalid attempts')
        for a in attempts:
            if set(a) != {'id','events'} or not re.fullmatch('[0-9a-f]{32}', a['id']) or a['id'] in seen:
                raise StateError('invalid attempt identity')
            seen.add(a['id'])
            if not isinstance(a['events'], list) or not a['events'] or a['events'][0]['outcome'] != 'in_flight':
                raise StateError('missing durable intent')
            for event in a['events']:
                if set(event) != {'outcome','reason','http_status','api_code','not_before','evidence','time'}:
                    raise StateError('invalid receipt')
                if event['outcome'] not in ('in_flight','confirmed','failed','unknown','waiting'):
                    raise StateError('invalid outcome')
                reasons={'intent','interrupted','observation_intent','api_ok','api_rejected','rate_limited',
                         'invalid_retry_after','invalid_json','invalid_api','inconsistent_response','http_ambiguous',
                         'transport_unknown','not_sent','invalid_result','bot_identity_mismatch',
                         'source_webhook_observed','target_identity_observed','target_identity_unresolved',
                         'target_configuration_observed','external_performed','external_not_performed','fixture_success'}
                if event['reason'] not in reasons:
                    raise StateError('invalid reason')
                if event['evidence'] is not None and not re.fullmatch('[0-9a-f]{64}',event['evidence']):
                    raise StateError('invalid evidence commitment')
                for n in ('http_status','api_code'):
                    if event[n] is not None and (type(event[n]) is not int or not 100 <= event[n] <= 599):
                        raise StateError('invalid response code')
                for n in ('time','not_before'):
                    if (n == 'not_before' and event[n] is None):
                        continue
                    if type(event[n]) not in (float,int) or not 0 <= event[n] <= 1e12:
                        raise StateError('invalid receipt time')
    return s


class Journal:
    def __init__(self, store, *, read_only=False):
        self.store = store
        self.key = store.binding_key(create=False) if read_only else store.binding_key()
        self.bot = None

    @contextlib.contextmanager
    def lock(self, bot_id):
        if self.bot is not None:
            raise StateError('nested lock')
        with self.store.lock(bot_id):
            self.bot = str(bot_id)
            try:
                yield self
            finally:
                self.bot = None

    def load(self, operation):
        envelope = self.store.read(operation)
        if set(envelope) != {'state','mac'}:
            raise StateError('invalid envelope')
        mac = fingerprint(self.key, canonical(envelope['state']))
        if not isinstance(envelope['mac'],str) or not hmac.compare_digest(mac,envelope['mac']):
            raise StateError('journal integrity failed')
        return _validate_state(envelope['state'])

    def save(self, state):
        _validate_state(state)
        if self.bot != state['plan']['bot_id']:
            raise StateError('per-bot lock required')
        previous=None
        try:
            os.stat(state['plan']['operation_id']+'.json',dir_fd=self.store._dirfd,follow_symlinks=False)
        except FileNotFoundError:
            pass
        except AttributeError:  # in-memory boundary double used by unit tests
            if state['plan']['operation_id'] in self.store.rows:
                previous=self.load(state['plan']['operation_id'])
        else:
            previous=self.load(state['plan']['operation_id'])
        if previous:
            snapshot_change = previous['snapshot'] != state['snapshot']
            if previous['snapshot'] is None and not any(previous['steps'].values()):
                snapshot_change = False  # one-time sealing of source observation after durable reservation
            if previous['digest']!=state['digest'] or previous['deployment']!=state['deployment'] or snapshot_change:
                raise StateError('immutable plan changed')
            for name in sids(state):
                old,new=previous['steps'][name],state['steps'][name]
                if len(new)<len(old):
                    raise StateError('attempt history cannot shrink')
                for a,b in zip(old,new):
                    if a['id']!=b['id'] or b['events'][:len(a['events'])]!=a['events']:
                        raise StateError('receipt history is append only')
            if 'superseded' in previous['checkpoints'] and state['checkpoints'].get('superseded')!=previous['checkpoints']['superseded']:
                raise StateError('superseded plan cannot be reopened')
        self.store.write(state['plan']['operation_id'],
                         {'state':state,'mac':fingerprint(self.key,canonical(state))})

    def create(self, plan, snapshot, *, deployment=None):
        validate_plan(plan)
        if self.bot != plan['bot_id']:
            raise StateError('per-bot lock required')
        # Never reinterpret corrupt/unknown files as a fresh operation.
        for path in self.store.root.glob('*.json'):
            existing = self.load(path.stem)
            if existing['plan']['operation_id'] == plan['operation_id']:
                raise StateError('operation already exists')
            if (existing['plan']['bot_id'] == self.bot and existing['results']['migration_outcome'] != 'confirmed'
                    and 'superseded' not in existing['checkpoints']):
                raise StateError('unfinished operation already exists')
        s = dict(schema_version=SCHEMA_VERSION,plan=copy.deepcopy(plan),digest=plan_digest(plan),
                 steps={step:[] for step in sids({'plan':plan})},checkpoints={},snapshot=snapshot,deployment=deployment,
                 results=dict(service_readiness='confirmed',migration_outcome='pending',
                              webhook_configuration='pending',delivery_verification='NOTRUN'))
        self.save(s)
        return s

    def checkpoint(self, s, name, receipt):
        if name not in ('confirmed','quiescence','endpoint_change','application_start','target_verified','delivery','superseded','state_transfer') or not receipt:
            raise StateError('explicit checkpoint receipt required')
        commitment=fingerprint(self.key,receipt)
        if name in ('confirmed','endpoint_change','application_start','superseded') and name in s['checkpoints']:
            if s['checkpoints'][name]['commitment']!=commitment:
                raise StateError('checkpoint already recorded with a different receipt')
            return
        s['checkpoints'][name] = {'commitment':commitment,'time':time.time()}
        self.save(s)

    def supersede(self,s,new_operation):
        if any(s['steps'].values()) or self.bot!=s['plan']['bot_id'] or new_operation==s['plan']['operation_id']:
            raise StateError('only a plan without any mutation attempt may be superseded')
        self.checkpoint(s,'superseded',_name(new_operation))
        s['results']['migration_outcome']='failed'
        self.save(s)

    def recover(self, s):
        for step in sids(s):
            if self.outcome(s,step) == 'in_flight':
                self.finish(s,step,'unknown','interrupted')

    def reconciliation_intent(self,s,step):
        if self.outcome(s,step)!='unknown':
            raise StateError('unknown attempt required')
        s['steps'][step][-1]['events'].append(self._event('in_flight','observation_intent'))
        self.save(s)

    @staticmethod
    def outcome(s, step):
        attempts = s['steps'][step]
        return attempts[-1]['events'][-1]['outcome'] if attempts else 'pending'

    def intent(self, s, step):
        if 'superseded' in s['checkpoints']:
            raise StateError('superseded plan cannot run')
        ids = sids(s)
        index = ids.index(step)
        if any(self.outcome(s,p) != 'confirmed' for p in ids[:index]):
            raise StateError('prerequisite not confirmed')
        if self.outcome(s,step) not in ('pending','failed','waiting'):
            raise StateError('unsafe attempt repetition')
        if self.outcome(s,step) == 'waiting':
            until = s['steps'][step][-1]['events'][-1]['not_before']
            if until is None or time.time() < until:
                raise StateError('retry not before deadline')
        attempt = secrets.token_hex(16)
        s['steps'][step].append({'id':attempt,'events':[self._event('in_flight','intent')]})
        self.save(s)  # send is permitted only after this returns successfully
        return attempt

    @staticmethod
    def _event(outcome,reason,*,http_status=None,api_code=None,not_before=None,evidence=None):
        return dict(outcome=outcome,reason=reason,http_status=http_status,api_code=api_code,
                    not_before=not_before,evidence=evidence,time=time.time())

    def finish(self,s,step,outcome,reason,**metadata):
        previous = self.outcome(s,step)
        if previous not in ('in_flight','unknown') or outcome not in ('confirmed','failed','unknown','waiting'):
            raise StateError('invalid receipt transition')
        if previous == 'unknown' and (outcome not in ('confirmed','failed') or not metadata.get('evidence')):
            raise StateError('independent reconciliation evidence required')
        s['steps'][step][-1]['events'].append(self._event(outcome,reason,**metadata))
        self.save(s)
