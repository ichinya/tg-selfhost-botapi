"""Cross-surface contracts that can also be checked on a native Windows host."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def published_blocks(language):
    text = (ROOT / 'docs' / language / 'migration.md').read_text(encoding='utf-8')
    return dict(re.findall(r'<!-- issue10-example:(\w+) -->\s*```sh\s*(.*?)```', text, re.S))


class ContractTests(unittest.TestCase):
    def test_both_locales_publish_the_same_two_executable_examples(self):
        english, russian = published_blocks('en'), published_blocks('ru')
        self.assertEqual(set(english), {'environment', 'positional'})
        self.assertEqual(english, russian)
        for block in english.values():
            self.assertIn('http://127.0.0.1:18080', block)
            self.assertIn('https://example.com/telegram/webhook', block)
            self.assertIn('"$BOT_TOKEN"', block)

    def test_external_internal_and_entrypoint_ports_agree(self):
        compose = (ROOT / 'docker-compose.yml').read_text(encoding='utf-8')
        nginx = (ROOT / 'nginx.conf').read_text(encoding='utf-8')
        entrypoint = (ROOT / 'docker-entrypoint.sh').read_text(encoding='utf-8')
        self.assertIn('"18080:80"', compose)
        self.assertIn('listen 80;', nginx)
        self.assertIn('proxy_pass http://botapi:8081;', nginx)
        self.assertRegex(entrypoint, r'TELEGRAM_HTTP_PORT[^\n]*8081')

    def test_existing_standalone_migrator_url_is_kept(self):
        page = ROOT / 'tg_selfhost_botapi_migrator.html'
        html = page.read_text(encoding='utf-8')
        self.assertEqual(html.count('<script>'), 1)
        self.assertNotRegex(html, r'<script[^>]+src=')
        for language in ('en', 'ru'):
            doc = (ROOT / 'docs' / language / 'migration.md').read_text(encoding='utf-8')
            self.assertIn('../../tg_selfhost_botapi_migrator.html', doc)


if __name__ == '__main__':
    unittest.main()
