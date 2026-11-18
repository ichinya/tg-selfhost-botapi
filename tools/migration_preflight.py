"""Conservative, token-free readiness evidence checks.

Network probing and deployment-specific verification must be supplied by the
caller. A protocol response alone never authorizes a source mutation.
"""
import json

from migration_contract import Outcome


def protocol_probe(status, content_type, body):
    from migration_readiness import is_ready
    return is_ready(status, content_type, body)


def readiness(*, protocol_ok, deployment_verified, credentials_ready, state_ready):
    """Fail closed unless independently verified evidence is explicitly supplied."""
    evidence = (protocol_ok, deployment_verified, credentials_ready, state_ready)
    if any(type(item) is not bool for item in evidence):
        raise ValueError('readiness evidence must be explicit booleans')
    return Outcome.CONFIRMED if all(evidence) else Outcome.BLOCKED
