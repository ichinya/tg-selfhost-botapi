from datetime import datetime,timezone,timedelta
import unittest
from unittest.mock import patch
from image_inputs import resolve

class RefreshTests(unittest.TestCase):
    def test_utc_generation_platform_and_stable_downloads(self):
        with patch('image_inputs.command',return_value='a'*40):
            def run(day=15,generation=0,platform='linux/amd64'):
                return resolve(clock=lambda:datetime(2026,11,day,tzinfo=timezone.utc),policy=dict(policy_version=1,refresh='utc-day',generation=generation),platform=platform)
            original=run()
            self.assertEqual(original['build_key'],run()['build_key'])
            for changed in (run(day=16),run(generation=1),run(platform='linux/arm64')):
                self.assertNotEqual(original['build_key'],changed['build_key'])
                self.assertEqual(original['downloads_key'],changed['downloads_key'])
            self.assertEqual(original['bot_api_revision'],'e3e9dd8e5b3d7ab8537cd5a10dc31d5ffa8f82d1')
