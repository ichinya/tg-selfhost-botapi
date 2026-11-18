"""Bounded stdlib HTTP transport, independent of other untracked candidates.

No proxy inheritance, redirects or retries. Tokens are carried only in the
protocol path in memory; exceptions and responses never become diagnostics.
"""
from dataclasses import dataclass
import http.client
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
from urllib.parse import urlencode, urlsplit
from migration_contract import normalize_endpoint,decode_json


@dataclass(frozen=True)
class Result:
    outcome: str
    reason: str
    status: int | None = None
    api_code: int | None = None
    not_before: float | None = None
    data: object = None
    content_type: str = ''
    body: bytes = b''
    sent_possible: bool = False


def classify(status, body, *, effect, content_type='', now=None):
    ambiguous = 'unknown' if effect else 'failed'
    if not 200 <= status < 500 or 300 <= status < 400:
        return Result(ambiguous,'http_ambiguous',status)
    try:
        p = decode_json(body)
    except (ValueError,UnicodeError,RecursionError):
        return Result(ambiguous,'invalid_json',status)
    if not isinstance(p,dict) or type(p.get('ok')) is not bool:
        return Result(ambiguous,'invalid_api',status)
    if p['ok'] and 200 <= status < 300 and 'result' in p:
        return Result('confirmed','api_ok',status,data=p['result'])
    code=p.get('error_code')
    if type(code) is not int or code != status or not 400 <= status < 500 or p['ok']:
        return Result(ambiguous,'inconsistent_response',status)
    if status == 429:
        params=p.get('parameters')
        retry=params.get('retry_after') if isinstance(params,dict) else None
        if type(retry) is not int or not 0 <= retry <= 86400:
            return Result(ambiguous,'invalid_retry_after',status,code)
        return Result('waiting','rate_limited',status,code,(time.time() if now is None else now)+retry)
    return Result('failed','api_rejected',status,code)


class Client:
    def __init__(self, *, connect_timeout=5, read_timeout=10, total_timeout=20,
                 body_limit=262144, fixture=False):
        if min(connect_timeout,read_timeout,total_timeout,body_limit) <= 0:
            raise ValueError('positive transport bounds required')
        self.connect_timeout=connect_timeout
        self.read_timeout=read_timeout
        self.total_timeout=total_timeout
        self.body_limit=body_limit
        self.fixture=fixture

    def request(self, endpoint, method=None, *, token=None, params=None, effect=False):
        endpoint=normalize_endpoint(endpoint)
        p=urlsplit(endpoint)
        if self.fixture and p.hostname not in ('127.0.0.1','::1'):
            raise ValueError('fixture loopback allowlist rejected endpoint')
        if method is not None and method not in ('getMe','getWebhookInfo','deleteWebhook','logOut','close','setWebhook'):
            raise ValueError('unsupported API method')
        if method and (not isinstance(token,str) or not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+',token)):
            raise ValueError('invalid token format')
        path=p.path.rstrip('/')+'/'
        if method:
            path+='bot'+token+'/'+method
        params = dict(params or {})
        if 'allowed_updates' in params:
            from migration_contract import canonical
            params['allowed_updates'] = canonical(params['allowed_updates'])
        content_type = 'application/x-www-form-urlencoded'
        certificate = params.pop('certificate_pem', None)
        if certificate is not None:
            import secrets
            if method != 'setWebhook' or not isinstance(certificate, str) or len(certificate) > 131072:
                raise ValueError('invalid certificate transport')
            boundary = 'migration-' + secrets.token_hex(24)
            parts = []
            for name, value in params.items():
                if not re.fullmatch('[a-z_]+', name):
                    raise ValueError('invalid profile field')
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
            parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="certificate"; filename="certificate.pem"\r\n'
                          f'Content-Type: application/x-pem-file\r\n\r\n{certificate}\r\n--{boundary}--\r\n').encode())
            data = b''.join(parts)
            content_type = 'multipart/form-data; boundary=' + boundary
        else:
            data=urlencode(params).encode('utf-8') if method else None
        if data is not None and len(data) > 262144:
            raise ValueError('request body limit')
        deadline=time.monotonic()+self.total_timeout
        # DNS resolution is bounded too; the detached resolver cannot send HTTP.
        resolved=[]
        done=threading.Event()
        def resolve():
            try:
                resolved.extend(socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM))
            except OSError:
                pass
            finally:
                done.set()
        threading.Thread(target=resolve,daemon=True).start()
        if not done.wait(min(self.connect_timeout,self.total_timeout)) or not resolved:
            return Result('failed','not_sent')
        conn=None
        raw=None
        timer=None
        sent=False
        try:
            for af,kind,proto,_,address in resolved:
                if time.monotonic() >= deadline:
                    return Result('failed','not_sent')
                if self.fixture and not ipaddress.ip_address(address[0]).is_loopback:
                    raise ValueError('fixture address rejected')
                raw=socket.socket(af,kind,proto)
                raw.settimeout(min(self.connect_timeout,max(.001,deadline-time.monotonic())))
                try:
                    raw.connect(address)
                    break
                except OSError:
                    raw.close()
                    raw=None
            if raw is None:
                return Result('failed','not_sent')
            if p.scheme=='https':
                raw=ssl.create_default_context().wrap_socket(raw,server_hostname=p.hostname)
            raw.settimeout(min(self.read_timeout,max(.001,deadline-time.monotonic())))
            conn=http.client.HTTPConnection(p.hostname, p.port, timeout=self.read_timeout)
            conn.sock=raw
            def expire():
                try:
                    raw.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            timer=threading.Timer(max(.001,deadline-time.monotonic()),expire)
            timer.daemon=True
            timer.start()
            sent=True
            conn.request('POST' if method else 'GET',path,body=data,
                         headers={'Content-Type':content_type,'Connection':'close'})
            response=conn.getresponse()
            chunks=[]
            size=0
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0:
                    raise TimeoutError()
                raw.settimeout(min(self.read_timeout,remaining))
                chunk=response.read1(min(65536,self.body_limit+1-size))
                size+=len(chunk)
                if size>self.body_limit:
                    raise ValueError('response_limit')
                if not chunk:
                    if response.length is not None and response.length>0:
                        raise http.client.IncompleteRead(b'')
                    break
                chunks.append(chunk)
                if response.isclosed() or response.length==0:
                    if response.length is not None and response.length>0:
                        raise http.client.IncompleteRead(b'')
                    break
            body=b''.join(chunks)
            content_type=response.getheader('Content-Type','')
            if method:
                result=classify(response.status,body,effect=effect,content_type=content_type)
                if result.outcome=='confirmed' and method in ('deleteWebhook','logOut','close','setWebhook') and result.data is not True:
                    return Result('unknown' if effect else 'failed','invalid_result',response.status,sent_possible=True)
                return result
            return Result('confirmed','probe_response',response.status,content_type=content_type,body=body,sent_possible=True)
        except (OSError,ValueError,http.client.HTTPException):
            return Result('unknown' if effect and sent else 'failed',
                          'transport_unknown' if sent else 'not_sent',sent_possible=sent)
        finally:
            if timer:
                timer.cancel()
            if conn:
                conn.close()
            elif raw:
                raw.close()
