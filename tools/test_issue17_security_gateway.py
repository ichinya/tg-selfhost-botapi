import contextlib
import io
from pathlib import Path
import socket
import threading
import unittest
from doctor_checks import nginx_tree, nginx_routes, nginx_privacy
from migration_helper import Server

ROOT=Path(__file__).resolve().parents[1]


class GatewayPolicy(unittest.TestCase):
    def test_effective_policy_and_unknown_override(self):
        config=(ROOT/'nginx-main.conf').read_text().replace('include /etc/nginx/conf.d/*.conf;', (ROOT/'nginx.conf').read_text())
        tree=nginx_tree(config)
        self.assertTrue(nginx_privacy(tree))
        self.assertFalse(nginx_routes(tree)[-1])
        self.assertFalse(nginx_privacy(nginx_tree(config+'error_log stderr crit;')))
        self.assertFalse(nginx_privacy(nginx_tree(config.replace('default other','default $uri'))))
        combined = config.replace('server {', (ROOT/'nginx.observability.conf').read_text() + '\nserver {', 1)
        self.assertTrue(nginx_privacy(nginx_tree(combined)))
        self.assertFalse(nginx_routes(nginx_tree(combined))[-1])

    def test_real_helper_malformed_requests_and_worker_exception_are_quiet(self):
        marker='synthetic_private_path'
        output=io.StringIO()
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
            server=Server(object(),0)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with socket.create_connection(server.server_address,timeout=3) as client:
                    client.sendall(('PRIVATE /'+marker+' HTTP/1.0\r\nHost: '+marker+'\r\n\r\n').encode())
                    self.assertIn(b'501',client.recv(4096))
                # Base socketserver normally prints the current exception here.
                try: raise ValueError(marker)
                except ValueError: server.handle_error(None,None)
            finally:
                server.shutdown();server.server_close();thread.join(3)
        self.assertEqual(output.getvalue(),'')
