"""Safe, typed classification of Bot API transport results.

This module is not yet a network client. A caller must distinguish a proven
failure before sending from a failure after sending might have started.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json

from migration_contract import Outcome


@dataclass(frozen=True)
class TransportResult:
    outcome: Outcome
    reason: str
    http_status: int | None = None
    api_error_code: int | None = None
    not_before: datetime | None = None


def classify_response(status, body, *, mutation, now=None):
    from migration_http import classify
    if type(status) is not int or not 100 <= status <= 599 or type(mutation) is not bool or not isinstance(body, bytes):
        raise ValueError('invalid transport response')
    if now is not None and now.tzinfo is None:
        raise ValueError('timezone aware time required')
    # Explicit clock override preserves this compatibility API's deterministic tests.
    if now is None:
        result = classify(status, body, effect=mutation)
    else:
        result = classify(status, body, effect=mutation, now=now.timestamp())
    deadline = datetime.fromtimestamp(result.not_before, timezone.utc) if result.not_before is not None else None
    return TransportResult(Outcome(result.outcome), result.reason, result.status, result.api_code, deadline)


def classify_failure(*, mutation, sent_possible):
    if type(mutation) is not bool or type(sent_possible) is not bool:
        raise ValueError('explicit send state required')
    return TransportResult(Outcome.UNKNOWN if mutation and sent_possible else Outcome.FAILED,
                           'transport_unknown' if sent_possible else 'not_sent')
