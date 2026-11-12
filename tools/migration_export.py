"""Export the same sealed operation, never an independent curl executor."""
import shlex
import re
import hmac
from migration_contract import validate_plan, plan_digest


def export_operation(state):
    plan = validate_plan(state['plan'])
    digest = state.get('digest')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest) or not hmac.compare_digest(digest, plan_digest(plan)):
        raise ValueError('invalid plan digest')
    operation = shlex.quote(plan['operation_id'])
    base = 'python3 tools/migration_cli.py'
    common = f' --operation {operation} --state-dir "$MIGRATION_STATE_DIR"'
    return {'plan': plan, 'digest': state['digest'], 'authority': 'MIGRATION_STATE_DIR',
            'commands': [base + ' status' + common,
                         base + ' apply' + common + ' --confirm-digest ' + shlex.quote(digest),
                         base + ' resume' + common],
            'notice': 'Use the existing private authority and runtime inputs. Export does not create or import state.'}
