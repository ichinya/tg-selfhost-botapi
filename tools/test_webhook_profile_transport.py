"""Real canonical URL-encoded and multipart wire contract."""
import json, threading, unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import parse_qs
from migration_http import Client
class TransportTests(unittest.TestCase):
    def test_full_profile_wire_and_secret_never_returned_as_diagnostics(self):
        records=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                records.append((self.headers.get('Content-Type'),self.rfile.read(int(self.headers['Content-Length']))))
                body=b'{"ok":true,"result":true}'
                self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self,*_): pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            for certificate in (None,'-----BEGIN CERTIFICATE-----\nsynthetic\n-----END CERTIFICATE-----'):
                params=dict(url='https://receiver.example',secret_token='secret_canary',allowed_updates=['message'],max_connections=40)
                if certificate: params['certificate_pem']=certificate
                result=Client(fixture=True).request('http://127.0.0.1:'+str(server.server_port),'setWebhook',token='123:synthetic',params=params,effect=True)
                self.assertEqual(result.outcome,'confirmed'); self.assertNotIn('secret_canary',repr(result))
                content,body=records[-1]
                if certificate:
                    self.assertTrue(content.startswith('multipart/form-data; boundary='))
                    self.assertIn(b'name="certificate"; filename="certificate.pem"',body)
                    self.assertIn(certificate.encode(),body)
                else:
                    values=parse_qs(body.decode()); self.assertEqual(values['secret_token'],['secret_canary']); self.assertEqual(json.loads(values['allowed_updates'][0]),['message'])
        finally: server.shutdown();server.server_close();thread.join(3)
