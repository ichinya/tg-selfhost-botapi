from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_observer_has_only_dedicated_inputs(self):
        text = (ROOT/'docker-compose.yml').read_text()
        section = text.split('  observer:')[1].split('  gateway:')[0]
        self.assertIn('network_mode: service:botapi', section)
        for bad in ['docker.sock', './data:', '/var/lib/telegram-bot-api', 'ports:', 'privileged:', 'pid:']:
            self.assertNotIn(bad, section)
        self.assertIn('read_only: true', section)
        self.assertIn('18081:81', text)

    def test_build_context_is_allowlisted(self):
        text = (ROOT/'.dockerignore').read_text()
        self.assertTrue(text.startswith('*\n'))
        self.assertIn('!tools/botapi_healthcheck.sh', text)
        self.assertNotIn('!tools/**', text)
