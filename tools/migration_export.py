"""Export the same sealed operation, never an independent curl executor."""
import shlex
import re
from migration_contract import validate_plan


def export_operation(state):
    plan = validate_plan(state['plan'])
    if not isinstance(state.get('digest'), str) or not re.fullmatch('[0-9a-f]{64}', state['digest']):
        raise ValueError('invalid export digest')
    operation = shlex.quote(plan['operation_id'])
    base = 'python3 tools/migration_cli.py'
    common = f' --operation {operation} --state-dir "$MIGRATION_STATE_DIR"'
    return {'plan': plan, 'digest': state['digest'], 'authority': 'MIGRATION_STATE_DIR',
            'commands': [base + ' status' + common,
                         base + ' apply' + common + ' --confirm-digest ' + state['digest'],
                         base + ' resume' + common],
            'notice': 'Use the existing private authority and runtime inputs. Export does not create or import state.'}
