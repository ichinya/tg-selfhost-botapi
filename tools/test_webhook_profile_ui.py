from pathlib import Path
import json
import subprocess
import threading
import unittest
from tools.webhook_profile_http_mock import MockAPI
from tools.webhook_profile_receiver import Receiver

ROOT = Path(__file__).resolve().parents[1]


class ProfileUITests(unittest.TestCase):
    def test_resolver_rejects_invalid_certificate(self):
        for body in ("PLACEHOLDER", "MAUwAwIBAQ=="):
            with self.subTest(body=body):
                profile = {"source": {"url": "https://example.invalid/hook", "max_connections": 40},
                           "desired": {"secret": {"mode": "none"}, "ip": {"mode": "dns"},
                                       "certificate": {"mode": "provided", "value": f"-----BEGIN CERTIFICATE-----\n{body}\n-----END CERTIFICATE-----"}}}
                result = subprocess.run(["node", "tools/webhook_profile_ui_harness.cjs", "--resolve"], cwd=ROOT,
                                        input=json.dumps([profile]), text=True, capture_output=True, timeout=20, check=True)
                self.assertEqual(json.loads(result.stdout)[0]["invalid"], ["certificate"])

    def test_inline_ui_negative_readback_privacy_matrix(self):
        result = subprocess.run(["node", "tools/webhook_profile_ui_harness.cjs"], cwd=ROOT,
                                text=True, capture_output=True, timeout=65)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actual_urlencoded_and_multipart_through_http_and_receiver(self):
        # This sender is a mock peer; receipt proves mock transport, not Telegram delivery.
        for encoding in ("urlencoded", "certificate"):
            with self.subTest(encoding=encoding), Receiver(b"Synthetic_secret_7", 701) as receiver:
                receiver_thread = threading.Thread(target=receiver.serve_forever, daemon=True)
                receiver_thread.start()
                try:
                    with MockAPI(receiver_port=receiver.server_port) as api:
                        thread = api.start()
                        try:
                            result = subprocess.run(["node", "tools/webhook_profile_ui_harness.cjs", "--http-case", api.base, encoding],
                                                    cwd=ROOT, text=True, capture_output=True, timeout=20)
                            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                            request = next(c for c in api.calls if c["method"] == "setWebhook")
                            self.assertEqual(request["fields"]["secret_token"], "Synthetic_secret_7")
                            self.assertEqual(request["fields"]["max_connections"], "7")
                            self.assertEqual(request["fields"]["ip_address"], "203.0.113.7")
                            self.assertEqual("certificate" in request["files"], encoding == "certificate")
                            if encoding == "certificate":
                                self.assertIn(b"BEGIN CERTIFICATE", request["files"]["certificate"])
                            self.assertEqual(len(receiver.receipts), 1)
                            self.assertEqual(receiver.receipts[0]["update_id"], 701)
                        finally:
                            api.shutdown()
                            thread.join(5)
                finally:
                    receiver.shutdown()
                    receiver_thread.join(5)


if __name__ == "__main__":
    unittest.main()
