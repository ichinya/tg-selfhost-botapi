"""Cross-surface contracts that can also be checked on a native Windows host."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def published_blocks(language):
    text = (ROOT / 'docs' / language / 'migration.md').read_text(encoding='utf-8')
    return dict(re.findall(r'<!-- issue10-example:(\w+) -->\s*```sh\s*(.*?)```', text, re.S))


class ContractTests(unittest.TestCase):
    def test_both_locales_document_explicit_plan_and_status(self):
        for language in ('en', 'ru'):
            text = (ROOT / 'docs' / language / 'migration.md').read_text(encoding='utf-8')
            for command in ('plan', 'status', 'apply', 'resume', 'export'):
                self.assertIn('migration_cli.py ' + command, text)

    def test_external_internal_and_entrypoint_ports_agree(self):
        compose = (ROOT / 'docker-compose.yml').read_text(encoding='utf-8')
        nginx = (ROOT / 'nginx.conf').read_text(encoding='utf-8')
        entrypoint = (ROOT / 'docker-entrypoint.sh').read_text(encoding='utf-8')
        self.assertIn('"${GATEWAY_BIND:-127.0.0.1}:18080:80"', compose)
        self.assertIn('listen 80;', nginx)
        self.assertIn('set $botapi_upstream http://botapi:8081;', nginx)
        self.assertIn('proxy_pass $botapi_upstream$request_uri;', nginx)
        self.assertIn('resolver 127.0.0.11', nginx)
        self.assertRegex(entrypoint, r'TELEGRAM_HTTP_PORT[^\n]*8081')

    def test_existing_standalone_migrator_url_is_kept(self):
        page = ROOT / 'tg_selfhost_botapi_migrator.html'
        html = page.read_text(encoding='utf-8')
        self.assertIn('assets/js/migration-client.mjs', html)
        for language in ('en', 'ru'):
            doc = (ROOT / 'docs' / language / 'migration.md').read_text(encoding='utf-8')
            self.assertIn('../../tg_selfhost_botapi_migrator.html', doc)


if __name__ == '__main__':
    unittest.main()
