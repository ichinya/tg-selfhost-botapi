"""Regression: the previous UA was rejected by the recipient's crawler filter."""
from pathlib import Path
import re
import unittest


class WebhookUserAgentTest(unittest.TestCase):
    def test_patched_user_agent_is_nonempty_and_neutral(self):
        patch = (Path(__file__).resolve().parents[1] / "patches/webhook-user-agent.patch").read_text()
        headers = re.findall(r'^\+\s*hc\.add_header\("User-Agent", "([^"\r\n]*)"\);', patch, re.MULTILINE)
        self.assertEqual(len(headers), 1)
        user_agent = headers[0]
        self.assertTrue(user_agent.strip())
        # lk.sipout.net rejected the old TelegramBotWebhook UA with HTTP 404.
        self.assertIsNone(re.search(r"bot|crawl|slurp|spider|mediapartners", user_agent, re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
