import http.client
import threading
import unittest
from observability.server import Collector, Server
from observability_mock_target import Handler, MARKER
from http.server import ThreadingHTTPServer


class HTTPTests(unittest.TestCase):
    def test_root_only_health_routes_methods_and_privacy(self):
        Handler.calls=[]; Handler.root_ok=True
        target=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=target.serve_forever,daemon=True).start()
        c=Collector('127.0.0.1',target.server_port)
        server=Server(('127.0.0.1',0),c)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            c.collect()
            for method,path,expected in [('GET','/health/live',200),('HEAD','/health/ready',200),('GET','/status',200),
                 ('GET','/status?token='+MARKER,404),('POST','/status',405),('GET','/inputs/credentials',404),
                 ('GET','/stats',404),('GET','/bot123/getMe',404)]:
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                conn.request(method,path,headers={'Authorization':MARKER})
                response=conn.getresponse(); body=response.read()
                self.assertEqual(response.status,expected)
                self.assertNotIn(MARKER,repr(response.getheaders())+body.decode())
                conn.close()
            self.assertEqual(Handler.calls,['root'])
            Handler.root_ok=False; c.collect()
            self.assertFalse(c.snapshot()['process']['live'])
            Handler.root_ok=True; c.collect(); self.assertTrue(c.snapshot()['process']['live'])
        finally:
            server.shutdown(); server.server_close(); target.shutdown(); target.server_close()
