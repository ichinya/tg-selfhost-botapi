"""Fail CI if the admitted executor depends on untracked workspace artifacts."""
from pathlib import Path
import subprocess
import sys
from check_migration_safety import PATTERNS

REQUIRED = ['migrate_off_to_self.sh','tg_selfhost_botapi_migrator.html','assets/js/migration-client.mjs',
            *('tools/migration_'+name+'.py' for name in ('contract','store','http','probe','engine','reconcile','cli','export','helper','mock','transport','readiness','preflight')),
            *('tools/'+pattern for pattern in PATTERNS), 'tools/test_migration_ui.mjs',
            'tools/check_docs.py','tools/check_migration_safety.py','tools/check_migration_volumes.py',
            'tools/migrator_request_mock.py',
            'tools/fixtures/migration/docker-compose.volumes.yml','tools/fixtures/migration/fake-bot-api.sh']


def main():
    root=Path(__file__).resolve().parents[1]
    tracked=subprocess.run(['git','ls-files','-z'],cwd=root,capture_output=True,check=True).stdout.decode().split('\0')
    missing=sorted(set(REQUIRED)-set(tracked))
    if missing:
        print('Migration dependencies missing from Git: '+', '.join(missing),file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
