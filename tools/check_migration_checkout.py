"""Fail CI if the admitted executor depends on untracked workspace artifacts."""
from pathlib import Path
import subprocess
import sys
from check_migration_safety import PATTERNS

REQUIRED = ['tools/migration_executor.sh','tools/migration_executor.html','migrate_off_to_self.sh','tg_selfhost_botapi_migrator.html','assets/js/migration-client.mjs',
            'nginx-main.conf','docker-compose.secrets.yml','patches/botapi-secrets-redaction.patch',
            'tools/issue17_security_gate.py','tools/issue17_security_checks.py',
            'tools/test_issue17_security_browser.cjs','tools/test_issue17_security_shell.cjs',
            *('tools/test_issue17_security_'+name+'.py' for name in ('inputs','exports','gateway','botapi','docs','matrix','gate','compose')),
            *('tools/fixtures/issue17_security/'+name for name in ('cases.json','mock_api.py','compose.yml','botapi_log_driver.cpp','README.md')),
            '.github/workflows/issue17-security.yml',
            *('tools/migration_'+name+'.py' for name in ('contract','store','http','probe','engine','reconcile','cli','export','helper','mock','transport','readiness','preflight')),
            *('tools/'+pattern for pattern in PATTERNS), 'tools/test_migration_ui.mjs',
            'tools/check_docs.py','tools/check_migration_safety.py','tools/check_migration_volumes.py',
            'tools/migrator_request_mock.py', 'tools/migrator_ui_harness.js', 'tools/html_migrator_mock.js',
            'tools/test_html_migrator.cjs', 'tools/test_html_migrator.py', 'tools/test_migrator_ui.py',
            'tools/issue8_shell_harness.cjs', 'tools/fixtures/issue8-shell-cases.json',
            'tools/issue10_ui_harness.cjs', 'tools/webhook_profile_http_mock.py',
            'tools/webhook_profile_runtime.sh', 'tools/webhook_profile_resolver.js',
            'tools/migration_diagnostics_main.sh', 'tools/embed_webhook_profile.cjs',
            '.github/workflows/html-migrator.yml', '.github/workflows/migration-safety.yml',
            'tools/fixtures/migration/docker-compose.volumes.yml','tools/fixtures/migration/fake-bot-api.sh',
            'tools/fixtures/migration-executor-cases.json','.github/workflows/migration-executor.yml']


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
