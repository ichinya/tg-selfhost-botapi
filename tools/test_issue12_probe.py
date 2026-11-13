import json
from email.message import Message
import unittest
from webhook_probe import validate_post, UA


class ProductionPostTests(unittest.TestCase):
    def test_nonce_and_one_user_agent_required(self):
        headers = Message()
        headers['Content-Type'] = 'application/json'
        headers['User-Agent'] = UA
        body = json.dumps({'update_id': 1, 'message': {'message_id': 1, 'text': 'release-probe-nonce'}})
        validate_post('POST', headers, body, nonce='nonce')
        for method, nonce in (('GET', 'nonce'), ('POST', 'wrong')):
            with self.assertRaises(ValueError):
                validate_post(method, headers, body, nonce=nonce)
        headers['User-Agent'] = UA
        with self.assertRaises(ValueError):
            validate_post('POST', headers, body, nonce='nonce')
        del headers['User-Agent']
        with self.assertRaises(ValueError):
            validate_post('POST', headers, body, nonce='nonce')
