"""Operator-started, same-origin loopback UI over the canonical migration core."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import secrets
import threading
import time
import os
import stat
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from migration_cli import view
from migration_contract import canonical, decode_json, normalize_endpoint
from migration_engine import Engine, Runtime, Stop
from migration_export import export_operation
from migration_http import Client
from migration_probe import Readiness, CloudReadiness, private_json
from migration_reconcile import TrustedReceipts, apply_external, apply_delivery
from migration_store import Journal, StateStore, StateError, _name

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {'/': ('tg_selfhost_botapi_migrator.html', 'text/html; charset=utf-8'),
          '/tg_selfhost_botapi_migrator.html': ('tg_selfhost_botapi_migrator.html', 'text/html; charset=utf-8'),
          '/assets/js/migration-client.mjs': ('assets/js/migration-client.mjs', 'text/javascript; charset=utf-8')}

BOOTSTRAP_TTL = 300
SESSION_TTL = 3600


def write_bootstrap(path, code, forbidden_roots):
    """Create a private bootstrap file outside the checkout and state mounts."""
    if os.name != 'posix':
        raise ValueError('bootstrap file requires Linux/WSL')
    path = Path(path).absolute()
    parent = path.parent.resolve(strict=True)
    if parent != path.parent:
        raise ValueError('bootstrap parent must not contain symlinks or traversal')
    for root in (ROOT, *forbidden_roots):
        root = Path(root).resolve()
        if parent == root or root in parent.parents:
            raise ValueError('bootstrap file must be outside checkout and state roots')
    directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(directory)
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError('bootstrap parent must be owned by operator with mode 0700')
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=directory)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(code + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory)
    finally:
        os.close(directory)


class Application:
    def __init__(self, config):
        fields={'state_dir','allowed_endpoints','evidence_file','trust_file','fixture'}
        if not isinstance(config,dict) or not fields <= set(config) or set(config)-fields-{'runtime','forbidden_state_roots'}:
            raise ValueError('invalid helper configuration')
        if type(config['fixture']) is not bool or not isinstance(config['allowed_endpoints'],list):
            raise ValueError('invalid helper endpoint policy')
        if not isinstance(config['evidence_file'], str) or not config['evidence_file'].strip():
            raise ValueError('evidence_file must be a non-empty path')
        self.config=config
        self.allowed={normalize_endpoint(v) for v in config['allowed_endpoints']}
        self.verifier=TrustedReceipts(private_json(config['trust_file'])) if config['trust_file'] else None
        self.inputs={}
        self.jobs={}
        self.guard=threading.Lock()
        self.slot=threading.BoundedSemaphore(1)
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='migration')

    @contextmanager
    def context(self, *, create=False):
        evidence=private_json(self.config['evidence_file']) if create and self.config['evidence_file'] else None
        roots=list(self.config.get('forbidden_state_roots',[]))
        if evidence:
            roots.extend(evidence['local_forbidden_roots'])
        store=StateStore(self.config['state_dir'],create=create,data_dirs=roots)
        try:
            yield Journal(store,read_only=not create), evidence
        finally:
            store.close()

    def runtime(self, operation, values=None):
        values=values or self.inputs.get(operation) or self.config.get('runtime')
        required={'source','target','token','profile','action'}
        optional={'drop','direction','local_mode','queue_ack','cloud_not_before'}
        if not isinstance(values,dict) or not required <= set(values) or set(values)-required-optional:
            raise ValueError('private runtime inputs required')
        if any(normalize_endpoint(values[k]) not in self.allowed for k in ('source','target')):
            raise ValueError('endpoint is not in the operator allowlist')
        runtime=Runtime(**values,fixture=self.config['fixture'])
        runtime.bot_id
        return runtime

    def engine(self,journal,runtime):
        client=Client(fixture=runtime.fixture)
        readiness=CloudReadiness(client,journal.key) if runtime.direction=='local_to_cloud' and not runtime.fixture else Readiness(client,lambda:private_json(self.config['evidence_file']),journal.key,state_root=journal.store.root)
        return Engine(journal,client,readiness,runtime,verifier=self.verifier)

    def status(self, operation, *, export=False):
        with self.context() as (journal,_):
            state=journal.load(operation)
            result=export_operation(state) if export else view(journal,state)
        if not export:
            with self.guard:
                result['job']=dict(self.jobs.get(operation,{'running':False}))
        return result

    def plan(self, body):
        operation=_name(body['operation_id'])
        runtime=self.runtime(operation,body.get('runtime'))
        with self.context(create=True) as (journal,_):
            with journal.lock(runtime.bot_id):
                path=journal.store.root/(operation+'.json')
                if path.exists():
                    state=journal.load(operation)
                    runtime.bind(state,journal.key)
                else:
                    state=self.engine(journal,runtime).prepare(operation,quiescence=body.get('quiescence'),
                                                              url_only_ack=body.get('ack_url_only') is True)
                self.inputs[operation]=body.get('runtime') or self.config.get('runtime')
                return view(journal,state)

    def submit(self, action, body):
        operation=_name(body['operation_id'])
        runtime=self.runtime(operation,body.get('runtime'))
        with self.context() as (journal,_):
            state=journal.load(operation)
            runtime.bind(state,journal.key)
            if body.get('digest') != state['digest']:
                raise ValueError('operation digest mismatch')
        with self.guard:
            if self.jobs.get(operation,{}).get('running'):
                return {'operation_id':operation,'running':True}
            if not self.slot.acquire(blocking=False):
                raise Stop('helper_busy')
            self.jobs[operation]={'running':True}
            try:
                self.pool.submit(self.perform,action,operation,runtime,dict(body))
            except Exception:
                del self.jobs[operation]
                self.slot.release()
                raise
        return {'operation_id':operation,'running':True}

    def perform(self, action, operation, runtime, body):
        result={'running':False,'exit_code':0}
        try:
            with self.context() as (journal,_):
                with journal.lock(runtime.bot_id):
                    state=journal.load(operation)
                    engine=self.engine(journal,runtime)
                    if action=='refresh':
                        engine.refresh(state)
                    elif action=='reconcile':
                        journal.recover(state)
                        if bool(body.get('evidence')) == bool(body.get('delivery')):
                            raise ValueError('select one receipt')
                        if body.get('evidence'):
                            apply_external(journal,state,body['evidence'],verifier=self.verifier)
                        else:
                            apply_delivery(journal,state,body['delivery'],verifier=self.verifier)
                    else:
                        engine.run(state,confirm_digest=body['digest'],quiescence=body.get('quiescence'),
                                   endpoint_change=body.get('endpoint_change'),application_start=body.get('application_start'),
                                   state_transfer=body.get('state_transfer'),resume=action=='resume')
        except Stop as exc:
            result.update(exit_code=exc.code,reason=exc.reason)
        except Exception:
            # Never log request bodies, tokens, private paths or exception text.
            result.update(exit_code=4,reason='invalid_input_or_state')
        finally:
            with self.guard:
                self.jobs[operation]=result
            self.slot.release()

    def close(self):
        self.pool.shutdown(wait=True)


class Server(ThreadingHTTPServer):
    daemon_threads=True
    request_queue_size=8
    def handle_error(self, request, client_address):
        pass
    def __init__(self, app, port=8765):
        self.app=app
        self.bootstrap=secrets.token_urlsafe(32)
        self.bootstrap_expires=time.monotonic()+BOOTSTRAP_TTL
        self.sessions={}
        self.auth_lock=threading.Lock()
        self.login_attempts=0
        self.connections=threading.BoundedSemaphore(16)
        super().__init__(('127.0.0.1',port),Handler)
        self.origin='http://127.0.0.1:'+str(self.server_port)

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        super().process_request(request,client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request,client_address)
        finally:
            self.connections.release()


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'
    def setup(self):
        super().setup()
        self.connection.settimeout(10)
        def expire():
            import socket
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.deadline=threading.Timer(10,expire)
        self.deadline.daemon=True
        self.deadline.start()

    def finish(self):
        self.deadline.cancel()
        super().finish()

    def log_message(self,*args):
        pass

    def log_error(self,*args):
        pass

    def reply(self,status,payload,content='application/json; charset=utf-8',cookie=None):
        raw=payload if isinstance(payload,bytes) else canonical(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type',content)
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        if cookie:
            self.send_header('Set-Cookie',cookie)
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError,ConnectionError,OSError):
            pass  # browser disconnect does not cancel the independent engine job

    def session(self):
        try:
            cookie=SimpleCookie(self.headers.get('Cookie',''))
            token=cookie['migration_session'].value
        except (KeyError,ValueError):
            return None
        with self.server.auth_lock:
            session = self.server.sessions.get(token)
            if session is None:
                return None
            csrf, expires = session
            if time.monotonic() >= expires:
                del self.server.sessions[token]
                return None
            return csrf

    def allowed(self, write=False):
        if (len(self.path)>2048 or len(self.headers.get_all('Host',[]))!=1
                or self.headers['Host']!=urlsplit(self.server.origin).netloc):
            return False
        origin=self.headers.get('Origin')
        if (write and origin!=self.server.origin) or (origin and origin!=self.server.origin):
            return False
        return self.headers.get('Sec-Fetch-Site','same-origin') not in ('cross-site','same-site')

    def do_GET(self):
        if not self.allowed():
            self.reply(403,{'reason':'origin_or_host_rejected'})
            return
        parsed=urlsplit(self.path)
        if parsed.path in ASSETS and not parsed.query:
            name,content=ASSETS[parsed.path]
            self.reply(200,(ROOT/name).read_bytes(),content)
            return
        if parsed.path=='/api/hello' and not parsed.query:
            self.reply(200,{'protocol':'migration-helper-v1','authenticated':self.session() is not None})
            return
        session=self.session()
        if not session:
            self.reply(401,{'reason':'session_required'})
            return
        if parsed.path=='/api/session' and not parsed.query:
            self.reply(200,{'csrf':session})
            return
        try:
            if parsed.path not in ('/api/status','/api/export'):
                raise ValueError('unknown route')
            query=parse_qs(parsed.query,strict_parsing=True)
            if set(query)!={'operation'} or len(query['operation'])!=1:
                raise ValueError('invalid locator')
            operation=_name(query['operation'][0])
            self.reply(200,self.server.app.status(operation,export=parsed.path=='/api/export'))
        except Exception:
            self.reply(400,{'reason':'invalid_input_or_state'})

    def do_POST(self):
        if not self.allowed(write=True):
            self.reply(403,{'reason':'origin_or_host_rejected'})
            return
        try:
            if (self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[]))!=1
                    or self.headers.get('Content-Type')!='application/json'):
                raise ValueError('invalid framing')
            size=int(self.headers['Content-Length'])
            if not 0 < size <= 262144:
                raise ValueError('body limit')
            body=decode_json(self.rfile.read(size))
            if not isinstance(body,dict):
                raise ValueError('object required')
            if self.path=='/api/session':
                with self.server.auth_lock:
                    self.server.login_attempts+=1
                    if (set(body)!={'code'} or not isinstance(body['code'],str) or not self.server.bootstrap
                            or time.monotonic() >= self.server.bootstrap_expires
                            or self.server.login_attempts>5 or not secrets.compare_digest(body['code'],self.server.bootstrap)):
                        raise ValueError('invalid bootstrap')
                    self.server.bootstrap=None
                    token,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
                    self.server.sessions[token]=(csrf,time.monotonic()+SESSION_TTL)
                self.reply(200,{'csrf':csrf},cookie='migration_session='+token+'; HttpOnly; SameSite=Strict; Path=/; Max-Age='+str(SESSION_TTL))
                return
            csrf=self.session()
            if not csrf or not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),csrf):
                self.reply(403,{'reason':'session_or_csrf_required'})
                return
            routes={'/api/plan','/api/apply','/api/resume','/api/refresh','/api/reconcile'}
            if self.path not in routes:
                raise ValueError('unknown route')
            action=self.path.rsplit('/',1)[-1]
            permitted={'operation_id','runtime','quiescence','ack_url_only'} if action=='plan' else {
                'operation_id','runtime','digest','quiescence','endpoint_change','application_start','state_transfer','evidence','delivery'}
            if not {'operation_id'} <= set(body) or set(body)-permitted:
                raise ValueError('unknown request fields')
            if action=='plan':
                self.reply(200,self.server.app.plan(body))
            else:
                self.reply(202,self.server.app.submit(action,body))
        except Stop as exc:
            self.reply(409,{'reason':exc.reason,'exit_code':exc.code})
        except Exception:
            self.reply(400,{'reason':'invalid_input_or_state'})


def main():
    parser=argparse.ArgumentParser(description='Start private loopback migration UI (Linux/WSL).')
    parser.add_argument('--config',required=True)
    parser.add_argument('--bootstrap-file',required=True)
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    app=server=None
    try:
        app=Application(private_json(args.config))
        server=Server(app,args.port)
        write_bootstrap(args.bootstrap_file, server.bootstrap,
                        [app.config['state_dir'], *app.config.get('forbidden_state_roots', [])])
        print('Open '+server.origin+'; read the one-time code from the selected bootstrap file.',flush=True)
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    except Exception:
        print('Helper could not start; check private configuration and state authority.')
        return 4
    finally:
        if server:
            server.server_close()
        if app:
            app.close()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
