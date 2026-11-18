"""Stateful loopback-only Bot API and receiver fixtures. No real tokens."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import socket
import threading
import time
from urllib.parse import parse_qs

TOKEN='123:fixture_synthetic'


class Bot:
    def __init__(self,side,ledger=None):
        self.side=side
        self.ledger=ledger if ledger is not None else []
        self.url='https://fixture.example/old' if side=='source' else 'https://fixture.example/unrelated-target-webhook'
        self.identity=123
        self.active=side=='source'
        self.queue=[1,2]
        self.faults={}
        self.effects={'logOut':0,'close':0,'deleteWebhook':0,'setWebhook':0,'getMe':0,'drop':0}
        self.calls={}
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass
            def response(self,status,payload):
                data=json.dumps(payload).encode()
                self.send_response(status)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def do_GET(self):
                owner.ledger.append((owner.side,'probe',{}))
                if self.path!='/prefix/':
                    self.response(404,{'ok':False,'error_code':404})
                    return
                if owner.faults.get('probe')=='html':
                    self.send_response(404)
                    self.send_header('Content-Type','text/html')
                    self.end_headers()
                    self.wfile.write(b'<h1>nginx</h1>')
                    return
                self.response(404,{'ok':False,'error_code':404,'description':'fixture'})
            def do_POST(self):
                prefix='/prefix/bot'+TOKEN+'/'
                if not self.path.startswith(prefix):
                    self.response(401,{'ok':False,'error_code':401})
                    return
                method=self.path[len(prefix):]
                owner.calls[method]=owner.calls.get(method,0)+1
                params={k:v[0] for k,v in parse_qs(self.rfile.read(int(self.headers.get('Content-Length','0'))).decode()).items()}
                owner.ledger.append((owner.side,method,params))
                fault=owner.faults.get(method)
                if fault=='lost_unapplied':
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                if fault=='reject':
                    self.response(400,{'ok':False,'error_code':400})
                    return
                if fault=='429':
                    self.response(429,{'ok':False,'error_code':429,'parameters':{'retry_after':2}})
                    return
                if fault=='timeout':
                    time.sleep(.3)
                    return
                if owner.side=='source' and not owner.active:
                    self.response(401,{'ok':False,'error_code':401})
                    return
                result=True
                if method=='getMe':
                    owner.effects['getMe']+=1
                    owner.active=True
                    result={'id':owner.identity,'is_bot':True}
                elif method=='getWebhookInfo':
                    result={'url':owner.url,'pending_update_count':len(owner.queue),'has_custom_certificate':False}
                elif method in ('deleteWebhook','setWebhook'):
                    owner.effects[method]+=1
                    owner.url=params.get('url','') if method=='setWebhook' else ''
                    if params.get('drop_pending_updates')=='true':
                        owner.effects['drop']+=1
                        owner.queue.clear()
                elif method in ('logOut', 'close'):
                    owner.effects[method]+=1
                    owner.active=False
                else:
                    self.response(404,{'ok':False,'error_code':404})
                    return
                if fault=='lost_applied':
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                if fault=='malformed':
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"ok":true,')
                    return
                self.response(200,{'ok':True,'result':result})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.endpoint=f'http://127.0.0.1:{self.server.server_port}/prefix'

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def deployment(endpoint):
    return dict(version=1,endpoint=endpoint,created_at=time.time(),deployment_id='fixture-deployment',
                provenance='fixture-local-inspection',image_id='sha256:'+'1'*64,image_digest='sha256:'+'2'*64,
                config_digest='3'*64,credentials_configured=True,persistent_path='/fixture/data',temp_path='/fixture/temp',
                persistent_mount_id='fixture-data',temp_mount_id='fixture-temp',runtime_uid=1000,runtime_gid=1000,
                write_verified=True,local_forbidden_roots=[],local_mode=True)


class Receiver:
    def __init__(self):
        self.updates=[]
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass
            def do_POST(self):
                owner.updates.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(204)
                self.end_headers()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.port=self.server.server_port
    def close(self):
        self.server.shutdown()
        self.server.server_close()
