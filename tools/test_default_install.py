"""Contracts for the minimal installation and optional observability."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

class DefaultInstallTests(unittest.TestCase):
    def test_minimal_env_and_services(self):
        env = (ROOT / '.env.example').read_text()
        self.assertEqual(['API_ID', 'API_HASH'], re.findall(r'(?m)^([A-Z][A-Z0-9_]*)=', env))
        base = (ROOT / 'docker-compose.yml').read_text()
        self.assertEqual(['botapi', 'gateway'], re.findall(r'(?m)^  ([a-z][a-z0-9_]*):$', base.split('\nvolumes:')[0]))
        self.assertNotIn('18081', base)
        self.assertNotIn('build:', base)
        self.assertIn('TELEGRAM_STAT: "false"', base)
        self.assertNotIn('observer:', (ROOT / 'docker-compose.build.yml').read_text())

    def test_overlay_is_private(self):
        overlay = (ROOT / 'docker-compose.observability.yml').read_text()
        self.assertIn('${MGMT_BIND:-127.0.0.1}:18081:81', overlay)
        self.assertEqual(2, overlay.count('${TELEGRAM_STAT:-false}'))
