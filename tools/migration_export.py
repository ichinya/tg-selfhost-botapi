"""Export the same sealed operation, never an independent curl executor."""
import shlex
from migration_contract import validate_plan


def export_operation(state):
    plan = validate_plan(state['plan'])
    operation = shlex.quote(plan['operation_id'])
    base = 'python3 tools/migration_cli.py'
    common = f' --operation {operation} --state-dir "$MIGRATION_STATE_DIR"'
    return {'plan': plan, 'digest': state['digest'], 'authority': 'MIGRATION_STATE_DIR',
            'commands': [base + ' status' + common,
                         base + ' apply' + common + ' --confirm-digest ' + state['digest'],
                         base + ' resume' + common],
            'notice': 'Use the existing private authority and runtime inputs. Export does not create or import state.'}
