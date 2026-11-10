"""Compatibility API delegating to canonical token-free readiness."""
from migration_contract import normalize_endpoint
from migration_http import Result
from migration_probe import protocol_ok


def target_base(value):
    return normalize_endpoint(value) + '/'


def is_ready(status, content_type, body):
    return protocol_ok(Result('confirmed', 'probe_response', status, content_type=content_type, body=body))
