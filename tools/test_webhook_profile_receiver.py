import http.client
import json
import threading
import unittest
from tools.webhook_profile_receiver import Receiver, expected_secret


class ReceiverTests(unittest.TestCase):
    def test_input_contract(self):
        for env in ({}, {"WEBHOOK_SECRET_TOKEN": ""}, {"WEBHOOK_SECRET_TOKEN": "a\n"},
                    {"WEBHOOK_SECRET_TOKEN": "a", "WEBHOOK_SECRET_TOKEN_FILE": "placeholder"}):
            with self.subTest(env=list(env)), self.assertRaises(ValueError):
                expected_secret(env)
        self.assertEqual(expected_secret({"WEBHOOK_SECRET_TOKEN": "Synthetic_secret"}), b"Synthetic_secret")

    def test_receipt_and_negative_headers(self):
        with Receiver(b"Synthetic_secret", 701) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for values, code in (([], 403), (["wrong"], 403), (["Synthetic_secret"] * 2, 403), (["Synthetic_secret"], 200)):
                    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                    body = b'{"update_id":701,"message":{"text":"synthetic"}}'
                    conn.putrequest("POST", "/receipt")
                    conn.putheader("Content-Length", str(len(body)))
                    for value in values:
                        conn.putheader("X-Telegram-Bot-Api-Secret-Token", value)
                    conn.endheaders(body)
                    response = conn.getresponse()
                    self.assertEqual(response.status, code)
                    data = response.read()
                    self.assertNotIn(b"Synthetic_secret", data)
                    self.assertNotIn(b"synthetic", data)
                    conn.close()
                self.assertEqual(len(server.receipts), 1)
                self.assertEqual(server.receipts[0]["update_id"], 701)
                self.assertTrue(server.receipts[0]["secret_matched"])
            finally:
                server.shutdown()
                thread.join(5)


if __name__ == "__main__":
    unittest.main()
