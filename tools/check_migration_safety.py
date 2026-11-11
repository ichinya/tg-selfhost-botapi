"""Run only admitted #2 tests; required POSIX gate fails on any skip."""
import argparse
import os
from pathlib import Path
import sys
import unittest

PATTERNS=('test_migration_contract.py','test_migration_store.py','test_migration_state_privacy.py',
          'test_migration_http.py','test_migration_engine.py','test_migration_reconcile.py',
          'test_migration_cli.py','test_migration_integration.py','test_migration_volumes.py',
          'test_migration_helper.py','test_migration_export.py','test_migration_interfaces.py',
          'test_migration_faults.py','test_migration_transport.py','test_migration_preflight.py',
          'test_migration_readiness.py','test_docs_privacy.py','test_migrator_requests.py',
          'test_migration_directions.py','test_issue17_security_inputs.py','test_issue17_security_exports.py')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--require-posix',action='store_true')
    args=p.parse_args()
    if args.require_posix and os.name!='posix':
        print('POSIX safety gate required; run in Linux/WSL',file=sys.stderr)
        return 1
    suite=unittest.TestSuite()
    for pattern in PATTERNS:
        suite.addTests(unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern=pattern))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() and (not args.require_posix or not result.skipped) else 1


if __name__=='__main__':
    raise SystemExit(main())
