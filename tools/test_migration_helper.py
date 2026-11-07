import http.client
import json
import threading
import unittest
from migration_helper import Server


class StubApplication:
    def __init__(self):
        self.effects=0
    def status(self, operation, export=False):
        return {'operation_id':operation,'steps':{},'effects':self.effects}
    def submit(self, action, body):
        self.effects+=1
        return {'operation_id':body['operation_id'],'running':True}


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.app=StubApplication()
        self.server=Server(self.app,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.cookie=''
        self.csrf=''

    def call(self,method,path,body=None,**extra):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        headers={'Origin':self.server.origin,'Content-Type':'application/json'}
        if self.cookie:
            headers.update(Cookie=self.cookie,**{'X-CSRF-Token':self.csrf})
        headers.update(extra)
        connection.request(method,path,json.dumps(body) if body is not None else None,headers)
        response=connection.getresponse()
        status,cookie=response.status,response.getheader('Set-Cookie')
        result=response.read()
        connection.close()
        return status,cookie,result

    def login(self):
        code=self.server.bootstrap
        status,cookie,body=self.call('POST','/api/session',{'code':code})
        self.assertEqual(status,200)
        self.assertIn('HttpOnly',cookie)
        self.assertIn('SameSite=Strict',cookie)
        self.cookie=cookie.split(';')[0]
        self.csrf=json.loads(body)['csrf']
        self.assertIsNone(self.server.bootstrap)
        self.assertEqual(self.call('POST','/api/session',{'code':code})[0],400)

    def test_session_host_origin_csrf_and_closed_routes(self):
        self.assertEqual(self.call('GET','/api/status?operation=op')[0],401)
        self.login()
        self.assertEqual(self.call('GET','/api/status?operation=op')[0],200)
        body={'operation_id':'op','digest':'a'*64}
        self.assertEqual(self.call('POST','/api/apply',body,Origin='null')[0],403)
        self.assertEqual(self.call('POST','/api/apply',body,Host='evil.example')[0],403)
        self.assertEqual(self.call('POST','/api/apply',body,**{'X-CSRF-Token':'wrong'})[0],403)
        self.assertEqual(self.call('POST','/api/apply',{**body,'command':'docker exec anything'})[0],400)
        self.assertEqual(self.app.effects,0)
        self.assertEqual(self.call('POST','/api/apply',body)[0],202)
        self.assertEqual(self.app.effects,1)

    def test_paths_and_private_outputs_are_not_served(self):
        self.login()
        for path in ('/.env','/binding.key','/../tools/migration_cli.py','/api/status?operation=../secret','/api/status?operation=op&url=secret'):
            self.assertEqual(self.call('GET',path)[0],400)
        status,_,body=self.call('GET','/api/hello')
        self.assertEqual(status,200)
        self.assertNotIn(b'csrf',body)
