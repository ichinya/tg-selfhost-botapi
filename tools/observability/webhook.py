"""Explicit ownership-gated getWebhookInfo; never a health dependency."""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import os
from pathlib import Path
import re
import time
from . import schema, probes
from .migration import read_json, read_migrations, permits_polling

REGISTRY = schema.object_schema(dict(schema_version=dict(type='integer', const=1), enabled=dict(type='boolean'),
    instance=dict(type='string', pattern=r'^[0-9a-f]{64}$', maxLength=64), allow_unobserved_migration=dict(type='boolean'),
    bots=dict(type='array', maxItems=100, items=schema.object_schema(dict(alias=schema.LABEL,
         credential_file=dict(type='string', pattern=r'^[A-Za-z0-9_-]{1,64}\.json$', maxLength=69))))))


def category(message):
    if not isinstance(message, str): raise ValueError('invalid_error')
    value = message.lower()
    if 'timeout' in value or 'timed out' in value: return 'timeout'
    if 'ssl' in value or 'tls' in value or 'certificate' in value: return 'tls'
    if re.search(r'\b4[0-9]{2}\b', value): return 'http_4xx'
    if re.search(r'\b5[0-9]{2}\b', value): return 'http_5xx'
    if 'connect' in value or 'resolve' in value: return 'connect'
    return 'unclassified_error'


def project(alias, payload):
    schema.alias(alias)
    if not isinstance(payload, dict) or payload.get('ok') is not True or not isinstance(payload.get('result'), dict):
        raise ValueError('api_unavailable')
    data = payload['result']
    if not isinstance(data.get('url'), str) or type(data.get('pending_update_count')) is not int:
        raise ValueError('invalid_webhook')
    pending = schema.count(data['pending_update_count'])
    error = schema.count(data.get('last_error_date'))
    sync = schema.count(data.get('last_synchronization_error_date'))
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    if any(v is not None and v > now + 5 for v in [error, sync]): raise ValueError('future_error')
    result = dict(alias=alias, state='last_error_recorded' if error else 'ready', reason='none',
        observed_at=schema.utcnow(), age_seconds=0, mode='webhook' if data['url'] else 'polling',
        pending_update_count=pending, last_error_date=error, last_error_age_seconds=max(0, now-error) if error else None,
        last_error_category=category(data.get('last_error_message', '')) if error else None,
        last_synchronization_error_date=sync, delivery_evidence='not_observed')
    return schema.validate(result, schema.BOT)


def allowed(registry, collector):
    from .runtime import read_runtime
    _, image = read_runtime(os.getenv('OBSERVER_RUNTIME_DIR') or None)
    if image['state'] != 'ready' or image['instance'] != registry['instance']: return False
    migration = read_migrations(os.getenv('OBSERVER_MIGRATION_DIR') or None)
    return registry['enabled'] and permits_polling(migration, registry['allow_unobserved_migration'])


def collect_webhooks(collector, registry_path=None):
    if not registry_path: return schema.observation('webhook', 'disabled', 'disabled', bots=[])
    registry = schema.validate(read_json(registry_path, private=True), REGISTRY)
    aliases = {bot['alias'] for bot in registry['bots']}
    collector.webhook_backoff = {k:v for k,v in collector.webhook_backoff.items()
                                if k[0] == registry['instance'] and k[1] in aliases and v > time.monotonic()}
    if len({b['alias'] for b in registry['bots']}) != len(registry['bots']): raise ValueError('duplicate_alias')
    if not allowed(registry, collector): return schema.observation('webhook', 'not_observed', 'ownership_required', bots=[])
    credentials = Path(os.getenv('OBSERVER_CREDENTIALS_DIR', '/inputs/credentials'))
    def one(bot):
        try:
            key = (registry['instance'], bot['alias'])
            if collector.webhook_backoff.get(key, 0) > time.monotonic(): return None
            # Recheck the current source/instance before each authenticated request.
            if not allowed(registry, collector): return None
            secret = read_json(credentials / bot['credential_file'], private=True, limit=1024)
            if not isinstance(secret, dict) or set(secret) != {'token'} or not isinstance(secret['token'], str) or not re.fullmatch(r'[0-9]{3,20}:[A-Za-z0-9_-]{6,128}', secret['token']):
                raise ValueError('invalid_credential')
            code, _, body = probes.request(collector.host, collector.port, '/bot' + secret['token'] + '/getWebhookInfo')
            # No retry in this cycle, including 429. The next cycle is >=60 s.
            import json
            if code == 429:
                try:
                    retry = json.loads(body).get('parameters', {}).get('retry_after')
                    if type(retry) is not int: retry = 60
                except (ValueError, AttributeError): retry = 60
                collector.webhook_backoff[key] = time.monotonic() + max(60, min(3600, retry))
                return None
            if code != 200:
                collector.webhook_backoff[key] = time.monotonic() + 60
                return None
            return project(bot['alias'], json.loads(body))
        except (OSError, ValueError, UnicodeError, OverflowError): return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        bots = [b for b in pool.map(one, registry['bots']) if b is not None]
    if not allowed(registry, collector): return schema.observation('webhook', 'not_observed', 'instance_changed', bots=[])
    complete = len(bots) == len(registry['bots'])
    return schema.observation('webhook', 'ready' if complete else 'unavailable', 'none' if complete else 'unexpected_response',
                              schema.utcnow() if bots or complete else None, 0 if bots or complete else None, bots=bots)
