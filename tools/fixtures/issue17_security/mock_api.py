"""Loopback/container-only mock. Private evidence stays on the temporary runner."""
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs

profile={'url':'','max_connections':40,'allowed_updates':[],'has_custom_certificate':False,'pending_update_count':0}
lock=threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def log_error(self,*args): pass
    def do_GET(self): self.handle_api()
    def do_POST(self): self.handle_api()
    def handle_api(self):
        data=self.rfile.read(int(self.headers.get('Content-Length','0')))
        evidence=Path(os.environ.get('EVIDENCE_DIR','/evidence'))
        with lock:
            evidence.mkdir(exist_ok=True)
            with (evidence/'requests.jsonl').open('a') as stream:
                stream.write(json.dumps({'path':self.path,'body':data.decode(errors='replace'),
                    'secret':self.headers.get('X-Telegram-Bot-Api-Secret-Token'),'method':self.command})+'\n')
        if '/reset/' in self.path:
            self.connection.close();return
        if '/delay/' in self.path: time.sleep(4)
        method=self.path.split('?')[0].rsplit('/',1)[-1]
        status=500 if '/fail/' in self.path else 200
        fields=parse_qs(data.decode(errors='replace'),keep_blank_values=True)
        if self.headers.get_content_type()=='multipart/form-data':
            message=BytesParser(policy=policy.default).parsebytes(('Content-Type: '+self.headers['Content-Type']+'\r\n\r\n').encode()+data)
            fields={p.get_param('name',header='content-disposition'):[p.get_payload(decode=True).decode(errors='replace')] for p in message.iter_parts()}
        with lock:
            if method=='setWebhook':
                profile.update(url=fields.get('url',[''])[0],max_connections=int(fields.get('max_connections',['40'])[0]),
                    allowed_updates=json.loads(fields.get('allowed_updates',['[]'])[0]),has_custom_certificate='certificate' in fields)
                result=True
            elif method=='deleteWebhook': profile['url']='';result=True
            elif method=='getWebhookInfo': result=dict(profile)
            elif method=='getMe': result={'id':123456789,'is_bot':True,'first_name':'Synthetic'}
            else: result=True
        body=json.dumps({'ok':True,'result':result}).encode()
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers()
        try:self.wfile.write(body)
        except (OSError,BrokenPipeError):pass


if __name__=='__main__':
    ThreadingHTTPServer(('0.0.0.0',8081),Handler).serve_forever()
