"""Shared vocabulary for a future migration executor.

This module defines data types only; it does not perform or resume migrations.
An unrecognised persisted schema must never be interpreted as a success.
"""

from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import json


# Lineage: ca34106 (#2). Version 2 deliberately rejects old source-drop plans.
SCHEMA_VERSION = 2
ENGINE_CONTRACT_VERSION = 2


class Direction(str, Enum):
    CLOUD_TO_LOCAL = "cloud_to_local"
    LOCAL_TO_LOCAL = "local_to_local"
    LOCAL_TO_CLOUD = "local_to_cloud"
    WEBHOOK_ONLY = "webhook_only"


class WebhookAction(str, Enum):
    PRESERVE = "preserve"
    SET = "set"
    POLLING = "polling"


class Outcome(str, Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    WAITING = "waiting"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class Aggregate(str, Enum):
    CONFIRMED = "confirmed"
    PARTIAL = "partial"
    BLOCKED = "blocked"


STEP_IDS = ('source_delete', 'source_logout', 'target_authorize', 'target_configure')


def step_ids(direction):
    """The only ordered protocol registry used by adapters and the journal."""
    return {
        'cloud_to_local': STEP_IDS,
        'local_to_local': ('source_delete', 'source_close', 'state_transfer', 'target_authorize', 'target_configure'),
        'local_to_cloud': STEP_IDS,
        'webhook_only': ('target_configure',),
    }[Direction(direction).value]


def registry(direction):
    ids = step_ids(direction)
    return [{'id': sid, 'dependencies': list(ids[i-1:i])} for i, sid in enumerate(ids)]


def normalize_endpoint(value):
    from urllib.parse import urlsplit, urlunsplit
    if not isinstance(value, str) or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValueError('invalid endpoint')
    try:
        p = urlsplit(value)
        if (p.scheme not in ('http', 'https') or not p.hostname or p.username is not None
                or p.password is not None or p.query or p.fragment or '%' in p.path
                or __import__('re').search(r'(^|/)bot[0-9]+:',p.path)
                or '\\' in value or any(c in ('.', '..') for c in p.path.split('/'))):
            raise ValueError('invalid endpoint')
        host = p.hostname.lower()
        if ':' in host:
            host = '[' + host + ']'
        if p.port is not None and p.port != (443 if p.scheme == 'https' else 80):
            host += ':' + str(p.port)
        return urlunsplit((p.scheme, host, p.path.rstrip('/'), '', ''))
    except (ValueError, TypeError) as exc:
        raise ValueError('invalid endpoint') from exc


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def decode_json(value):
    def unique(pairs):
        obj={}
        for key,item in pairs:
            if key in obj:
                raise ValueError('duplicate JSON key')
            obj[key]=item
        return obj
    def reject(_):
        raise ValueError('nonfinite JSON value')
    return json.loads(value,object_pairs_hook=unique,parse_constant=reject)


def validate_profile(profile, action):
    if action == 'polling' or action == 'preserve' and profile == {'mode': 'polling'}:
        if profile != {'mode': 'polling'}:
            raise ValueError('polling profile required')
    else:
        from urllib.parse import urlsplit
        allowed = {'mode', 'url', 'secret_token', 'allowed_updates', 'max_connections', 'ip_address', 'certificate_pem'}
        if (not isinstance(profile, dict) or set(profile) - allowed or not {'mode', 'url'} <= set(profile)
                or profile['mode'] not in ('url_only', 'full') or not isinstance(profile['url'], str)
                or profile['mode'] == 'url_only' and set(profile) != {'mode', 'url'}):
            raise ValueError('explicit typed webhook profile required')
        url = urlsplit(profile['url'])
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username
                or url.password or url.fragment or any(ord(c) < 33 for c in profile['url'])):
            raise ValueError('invalid webhook URL')
        url.port
        import re
        if 'secret_token' in profile and (not isinstance(profile['secret_token'], str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', profile['secret_token'])):
            raise ValueError('invalid webhook secret')
        if 'max_connections' in profile and (type(profile['max_connections']) is not int or not 1 <= profile['max_connections'] <= 100000):
            raise ValueError('invalid webhook connection limit')
        if 'allowed_updates' in profile and (not isinstance(profile['allowed_updates'], list)
                or any(not isinstance(v, str) or not re.fullmatch('[a-z_]{1,64}', v) for v in profile['allowed_updates'])
                or len(set(profile['allowed_updates'])) != len(profile['allowed_updates'])):
            raise ValueError('invalid allowed updates')
        if 'ip_address' in profile:
            import ipaddress
            ipaddress.IPv4Address(profile['ip_address'])
        if 'certificate_pem' in profile and (not isinstance(profile['certificate_pem'], str)
                or len(profile['certificate_pem']) > 131072
                or not profile['certificate_pem'].startswith('-----BEGIN CERTIFICATE-----')):
            raise ValueError('invalid certificate input')
    return canonical(profile)


def build_plan(*, operation_id, bot_id, source, target, token, profile, action, drop,
               key, direction='cloud_to_local', fixture=False, local_mode=True,
               queue_ack=False, cloud_not_before=None, deployment=None):
    from urllib.parse import urlsplit
    source, target = normalize_endpoint(source), normalize_endpoint(target)
    Direction(direction)
    if (source == target) != (direction == 'webhook_only'):
        raise ValueError('endpoint roles do not match direction')
    if direction == 'cloud_to_local' and source != 'https://api.telegram.org':
        if not fixture or urlsplit(source).hostname not in ('127.0.0.1', '::1'):
            raise ValueError('explicit cloud source required')
    if direction == 'local_to_cloud' and target != 'https://api.telegram.org':
        if not fixture or urlsplit(target).hostname not in ('127.0.0.1', '::1'):
            raise ValueError('explicit cloud target required')
    if direction == 'local_to_cloud' and (not queue_ack or local_mode):
        raise ValueError('cloud target and queue limitation acknowledgement required')
    if type(local_mode) is not bool or type(queue_ack) is not bool:
        raise ValueError('explicit capabilities required')
    if cloud_not_before is not None and (type(cloud_not_before) not in (int, float) or not 0 <= cloud_not_before <= 1e12):
        raise ValueError('invalid cloud cooldown')
    if cloud_not_before is not None:
        cloud_not_before = float(cloud_not_before)
    WebhookAction(action)
    if type(drop) is not bool or not isinstance(token, str) or not token:
        raise ValueError('invalid queue policy or token')
    profile_value = validate_profile(profile, action)
    plan = dict(operation_id=operation_id, bot_id=str(bot_id), direction=direction,
                engine_version=ENGINE_CONTRACT_VERSION, action=action, drop=drop, fixture=fixture,
                references={'source':'OLD_BOT_URL','target':'SELF_BOT_URL','token':'BOT_TOKEN',
                            'token_file':'BOT_TOKEN_FILE','webhook':'WEBHOOK_URL'},
                drop_step='target_configure' if drop else None,
                local_mode=local_mode, queue_ack=queue_ack, cloud_not_before=cloud_not_before,
                profile_scope=profile['mode'],
                deployment_fingerprint=deployment or fingerprint(key, 'unbound-deployment'),
                steps=registry(direction),
                **{n + '_fingerprint': fingerprint(key, v) for n, v in
                   (('source', source), ('target', target), ('token', token), ('profile', profile_value))})
    return validate_plan(plan)


@dataclass(frozen=True)
class Capabilities:
    """An explicit local-mode declaration, not inferred from the endpoint."""

    local_mode: bool

    def __post_init__(self):
        if type(self.local_mode) is not bool:
            raise ValueError("local_mode must be an explicit boolean")


@dataclass(frozen=True)
class Step:
    id: str
    dependencies: tuple[str, ...] = ()


class CheckpointKind(str, Enum):
    PLAN_CONFIRMATION = "plan_confirmation"
    QUIESCENCE = "quiescence"
    STATE_TRANSFER = "state_transfer"
    ENDPOINT_CHANGE = "endpoint_change"
    APPLICATION_START = "application_start"


@dataclass(frozen=True)
class WebhookProfile:
    """References and keyed fingerprints only; never raw webhook secrets."""

    url_fingerprint: str
    secret_fingerprint: str | None = None
    allowed_updates: tuple[str, ...] | None = None
    max_connections: int | None = None
    ip_fingerprint: str | None = None
    certificate_fingerprint: str | None = None


def fingerprint(key, value):
    """Bind an exact runtime value without storing it in the plan."""
    if not isinstance(key, bytes) or len(key) < 32 or not isinstance(value, str):
        raise ValueError("fingerprint requires a private key and text value")
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def plan_digest(redacted_plan):
    """Hash a caller-validated, redacted plan with deterministic encoding.

    This function does not redact input or validate the complete plan schema.
    Callers must not pass runtime credentials or sensitive URLs.
    """
    if not isinstance(redacted_plan, dict):
        raise ValueError("plan must be an object")
    try:
        encoded = json.dumps(redacted_plan, sort_keys=True, ensure_ascii=True,
                             separators=(",", ":"), allow_nan=False).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise ValueError("plan is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class Receipt:
    step_id: str
    attempt: int
    outcome: Outcome
    evidence_ref: str | None = None

    def __post_init__(self):
        if type(self.attempt) is not int or self.attempt < 1:
            raise ValueError("attempt must be a positive integer")
        if not isinstance(self.outcome, Outcome):
            raise ValueError("outcome must be an Outcome")
        if self.outcome is Outcome.CONFIRMED and not self.evidence_ref:
            raise ValueError("confirmed outcomes require evidence")


def validate_schema_version(version):
    """Reject incompatible or ambiguous schema versions before any network use."""
    if type(version) is not int or version != SCHEMA_VERSION:
        raise ValueError("unsupported migration schema version")


def import_legacy_state(_state):
    """No released legacy schema is available to import safely yet."""
    raise ValueError("legacy migration schema is not supported")


# Persisted plans use a deliberately closed schema: runtime secrets and URLs
# cannot accidentally be admitted as arbitrary extra properties.
_HEX = __import__('re').compile(r'[0-9a-f]{64}\Z')
_IDENTIFIER = __import__('re').compile(r'[A-Za-z0-9_-]{1,128}\Z')
_TRANSITIONS = {
    Outcome.PENDING: {Outcome.IN_FLIGHT, Outcome.WAITING, Outcome.BLOCKED},
    Outcome.WAITING: {Outcome.PENDING, Outcome.BLOCKED},
    Outcome.BLOCKED: {Outcome.PENDING},
    Outcome.IN_FLIGHT: {Outcome.CONFIRMED, Outcome.FAILED, Outcome.UNKNOWN, Outcome.WAITING},
    Outcome.FAILED: {Outcome.PENDING, Outcome.BLOCKED},
    Outcome.UNKNOWN: {Outcome.CONFIRMED, Outcome.FAILED, Outcome.BLOCKED},
    Outcome.CONFIRMED: set(),
    Outcome.SKIPPED: set(),
}


def validate_transition(previous, current, evidence=None):
    try:
        previous, current = Outcome(previous), Outcome(current)
    except (ValueError, TypeError) as exc:
        raise ValueError('invalid outcome') from exc
    if current not in _TRANSITIONS[previous]:
        raise ValueError('invalid outcome transition')
    if current is Outcome.CONFIRMED and (not isinstance(evidence, str) or not _IDENTIFIER.fullmatch(evidence)):
        raise ValueError('confirmation requires an evidence reference')
    if previous is Outcome.UNKNOWN and current is Outcome.FAILED and (not isinstance(evidence,str) or not _IDENTIFIER.fullmatch(evidence)):
        raise ValueError('rejection of unknown effect requires evidence')


def validate_plan(plan):
    fields = {'operation_id', 'bot_id', 'direction', 'engine_version', 'drop_step', 'references', 'fixture', 'source_fingerprint',
              'target_fingerprint', 'token_fingerprint', 'action', 'profile_fingerprint', 'drop', 'steps',
              'local_mode', 'queue_ack', 'cloud_not_before', 'deployment_fingerprint', 'profile_scope'}
    if not isinstance(plan, dict) or set(plan) != fields:
        raise ValueError('invalid plan fields')
    if type(plan['fixture']) is not bool:
        raise ValueError('invalid fixture boundary')
    if plan['references'] != {'source':'OLD_BOT_URL','target':'SELF_BOT_URL','token':'BOT_TOKEN',
                              'token_file':'BOT_TOKEN_FILE','webhook':'WEBHOOK_URL'}:
        raise ValueError('invalid private input references')
    if (type(plan['engine_version']) is not int or plan['engine_version'] != ENGINE_CONTRACT_VERSION
            or plan['direction'] not in tuple(d.value for d in Direction)):
        raise ValueError('unsupported engine or direction')
    for field in ('operation_id', 'bot_id'):
        if not isinstance(plan[field], str) or not _IDENTIFIER.fullmatch(plan[field]):
            raise ValueError('invalid identifier')
    if not __import__('re').fullmatch('[1-9][0-9]*', plan['bot_id']):
        raise ValueError('numeric bot identity required')
    if (plan['profile_scope'] not in ('polling','url_only','full')
            or plan['action'] == 'polling' and plan['profile_scope'] != 'polling'
            or plan['action'] == 'set' and plan['profile_scope'] == 'polling'):
        raise ValueError('invalid delivery profile scope')
    try:
        Direction(plan['direction'])
        WebhookAction(plan['action'])
    except (ValueError, TypeError) as exc:
        raise ValueError('invalid plan selection') from exc
    for field in ('source_fingerprint', 'target_fingerprint', 'token_fingerprint', 'profile_fingerprint', 'deployment_fingerprint'):
        if not isinstance(plan[field], str) or not _HEX.fullmatch(plan[field]):
            raise ValueError('invalid fingerprint')
    if type(plan['drop']) is not bool or not isinstance(plan['steps'], list) or not plan['steps']:
        raise ValueError('invalid plan')
    if plan['direction'] == 'webhook_only' and plan['action'] == 'preserve' and plan['drop']:
        raise ValueError('no-op preserve cannot drop pending updates')
    if plan['drop_step'] != ('target_configure' if plan['drop'] else None):
        raise ValueError('drop must occur only on target configuration')
    if type(plan['local_mode']) is not bool or type(plan['queue_ack']) is not bool:
        raise ValueError('invalid capabilities')
    if plan['direction'] == 'local_to_cloud' and (plan['local_mode'] or not plan['queue_ack']):
        raise ValueError('cloud migration acknowledgement required')
    if plan['cloud_not_before'] is not None and (type(plan['cloud_not_before']) not in (int, float)
            or not 0 <= plan['cloud_not_before'] <= 1e12):
        raise ValueError('invalid cooldown')
    expected = registry(plan['direction'])
    if plan['steps'] != expected or ((plan['source_fingerprint'] == plan['target_fingerprint']) != (plan['direction'] == 'webhook_only')):
        raise ValueError('invalid ordered migration steps')
    seen = set()
    for step in plan['steps']:
        if not isinstance(step, dict) or set(step) != {'id', 'dependencies'}:
            raise ValueError('invalid step')
        sid, dependencies = step['id'], step['dependencies']
        if not isinstance(sid, str) or not _IDENTIFIER.fullmatch(sid) or sid in seen:
            raise ValueError('duplicate or invalid step')
        if not isinstance(dependencies, list) or any(not isinstance(d, str) or d not in seen for d in dependencies) or len(set(dependencies)) != len(dependencies):
            raise ValueError('invalid step dependencies')
        seen.add(sid)
    return plan


def validate_binding(plan, digest, runtime_bindings, key):
    validate_plan(plan)
    if not isinstance(digest, str) or not hmac.compare_digest(plan_digest(plan), digest):
        raise ValueError('sealed plan digest mismatch')
    if not isinstance(runtime_bindings, dict) or set(runtime_bindings) != {'source', 'target', 'token', 'profile', 'action', 'drop'}:
        raise ValueError('invalid runtime bindings')
    for name in ('source', 'target', 'token', 'profile'):
        value = runtime_bindings[name]
        if name in ('source', 'target'):
            value = normalize_endpoint(value)
        if name == 'profile':
            value = validate_profile(value, plan['action'])
        if not hmac.compare_digest(plan[name + '_fingerprint'], fingerprint(key, value)):
            raise ValueError('runtime binding mismatch')
    if runtime_bindings['action'] != plan['action'] or type(runtime_bindings['drop']) is not bool or runtime_bindings['drop'] != plan['drop']:
        raise ValueError('runtime selection mismatch')


def validate_snapshot(snapshot):
    """Validate the complete journal and its attempt history before use."""
    if not isinstance(snapshot, dict) or set(snapshot) != {'schema_version', 'plan', 'digest', 'steps'}:
        raise ValueError('invalid snapshot fields')
    validate_schema_version(snapshot['schema_version'])
    plan = validate_plan(snapshot['plan'])
    digest = snapshot['digest']
    if not isinstance(digest, str) or not hmac.compare_digest(plan_digest(plan), digest):
        raise ValueError('invalid plan digest')
    steps = snapshot['steps']
    if not isinstance(steps, list) or len(steps) != len(plan['steps']):
        raise ValueError('invalid journal steps')
    for expected, record in zip(plan['steps'], steps):
        if not isinstance(record, dict) or set(record) != {'id', 'attempts'} or record['id'] != expected['id']:
            raise ValueError('invalid journal step')
        attempts = record['attempts']
        if not isinstance(attempts, list):
            raise ValueError('invalid attempts')
        for number, attempt in enumerate(attempts, 1):
            if not isinstance(attempt, dict) or set(attempt) != {'number', 'transitions'} or type(attempt['number']) is not int or attempt['number'] != number:
                raise ValueError('invalid attempt')
            transitions = attempt['transitions']
            if not isinstance(transitions, list) or not transitions:
                raise ValueError('invalid transition history')
            previous = Outcome.PENDING
            for transition in transitions:
                if not isinstance(transition, dict) or set(transition) != {'outcome', 'evidence'}:
                    raise ValueError('invalid transition record')
                evidence = transition['evidence']
                if evidence is not None and (not isinstance(evidence, str) or not _IDENTIFIER.fullmatch(evidence)):
                    raise ValueError('invalid evidence reference')
                validate_transition(previous, transition['outcome'], evidence)
                previous = Outcome(transition['outcome'])
            if number < len(attempts) and previous is not Outcome.FAILED:
                raise ValueError('attempt cannot be repeated')
    return snapshot
