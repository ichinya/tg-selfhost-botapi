"""Loopback receiver for the real C++ sender. Never sends synthetic HTTP itself."""
import argparse
import hashlib
import http.server
import json
from pathlib import Path
import subprocess
import threading
import time
import uuid

UA = 'WebhookDelivery/1.0'


def validate_post(method, headers, body, expected=UA, nonce=None):
    value = json.loads(body)
    if (method != 'POST' or headers.get_all('User-Agent', []) != [expected]
            or headers.get_content_type() != 'application/json'
            or not isinstance(value, dict) or type(value.get('update_id')) is not int
            or value.get('message') != {'message_id': 1, 'text': 'release-probe' + ('-' + nonce if nonce else '')}):
        raise ValueError('Production sender HTTP contract failed')


def probe(image, expected=UA, ack='success'):
    if ack not in ('success', 'error', 'timeout'):
        raise ValueError('Invalid ACK control')
    observation = {'received': False, 'valid': False, 'rejected': False}
    nonce = uuid.uuid4().hex
    container = 'botapi-sender-' + nonce

    class Receiver(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.connection.settimeout(2)
            observation['received'] = True
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096 or self.path != '/release-probe':
                    raise ValueError('Invalid synthetic request size/path')
                body = self.rfile.read(length)
                validate_post('POST', self.headers, body, expected, nonce)
                observation['valid'] = True
                observation['update_id'] = json.loads(body)['update_id']
                observation['request_sha256'] = hashlib.sha256(body).hexdigest()
                status = 503 if ack == 'error' else 200
            except (ValueError, TypeError, OSError):
                status = 400
                observation['rejected'] = True
            if ack == 'timeout':
                time.sleep(12)  # Sender's own deadline is ten seconds.
            try:
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'{}')
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def log_message(self, *args):
            pass

    with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Receiver) as server:
        server.timeout = 2
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # Linux qualification only: same loopback namespace, no public listener.
            command = ['docker', 'run', '--rm', '--name', container, '--network', 'host', '--cpus', '1', '--memory', '256m',
                       '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                       '--entrypoint', '/usr/local/libexec/release-webhook-sender', image, str(server.server_port), nonce]
            result = subprocess.run(command, capture_output=True, timeout=20)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            subprocess.run(['docker', 'rm', '-f', container], capture_output=True, timeout=15)
    acknowledged = result.returncode == 0 and json.loads(result.stdout).get('queue_acknowledged') is True
    if ack != 'success':
        if observation['received'] and observation['valid'] and not acknowledged and result.returncode == 1:
            return {'ack_' + ack + '_control': 'PASS'}
        raise ValueError('Failed/timed-out HTTP ACK was incorrectly accepted')
    if expected != UA:
        if observation['received'] and observation['rejected'] and not observation['valid'] and result.returncode == 1:
            return {'receiver_negative_control': 'PASS'}
        raise ValueError('Negative control did not observe a rejected POST and failed queue ACK')
    if not observation['received'] or not observation['valid'] or not acknowledged:
        raise ValueError('Sender behavior/queue acknowledgement NOT PASS')
    return {'contract': 1, 'user_agent': UA, 'production_sender': 'PASS', 'queue_acknowledged': True,
            'update_id': observation['update_id'], 'request_sha256': observation['request_sha256'],
            'live_delivery': 'NOTRUN'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config_id = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', args.image], text=True).strip()
    result = probe(config_id)
    result.update(probe(config_id, expected='WrongUA/negative-control'))
    result.update(probe(config_id, ack='error'))
    result.update(probe(config_id, ack='timeout'))
    result['image_config_id'] = config_id
    args.output.write_text(json.dumps(result, sort_keys=True) + '\n', encoding='utf8')
