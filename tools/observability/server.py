"""Read-only snapshot server. Slow authenticated diagnostics have a separate worker."""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import time
from . import probes, schema, stats


class Collector:
    def __init__(self, host='127.0.0.1', port=8081, stats_enabled=False):
        self.host, self.port = probes.target(host, port)
        self.stats_enabled = stats_enabled
        self.lock = threading.Lock()
        self.status = schema.empty_status(stats_enabled)
        self.last_attempt = None
        self.last_success = None
        self.stats_success = None
        self.tick = None
        self.stop = threading.Event()
        self.webhook_backoff = {}

    def collect(self):
        self.tick = time.monotonic()
        live = False
        manager = None
        try: live = probes.probe(self.host, self.port)
        except (OSError, ValueError, OverflowError): pass
        if self.stats_enabled:
            try: manager = stats.fetch()
            except (OSError, ValueError, OverflowError): pass
        now = time.monotonic()
        with self.lock:
            self.last_attempt = now
            if live: self.last_success = (now, schema.utcnow())
            if manager is not None: self.stats_success = (now, schema.utcnow())
            p = self.status['process']
            p.update(state='ready' if live and (manager is not None or not self.stats_enabled) else 'unavailable',
                     reason='none' if live and (manager is not None or not self.stats_enabled) else 'unexpected_response',
                     live=live, ready=live and (manager is not None or not self.stats_enabled))
            if self.last_success: p.update(observed_at=self.last_success[1], age_seconds=0)
            q = self.status['queue']
            q.update(state='ready' if manager else 'unavailable' if self.stats_enabled else 'disabled',
                     reason='none' if manager else 'unexpected_response' if self.stats_enabled else 'disabled')
            if manager:
                q.update(sampled=manager['queue'], observed_at=self.stats_success[1], age_seconds=0)
            elif self.stats_enabled:
                q['sampled'] = schema.empty_status()['queue']['sampled']

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            result = copy.deepcopy(self.status)
            for key, success in [('process', self.last_success), ('queue', self.stats_success)]:
                if success:
                    age, fresh = schema.freshness(success[0], now, 15)
                    result[key]['age_seconds'] = age
                    if not fresh:
                        result[key].update(state='stale', reason='stale')
                        if key == 'process': result[key].update(live=False, ready=False)
            # A stalled scheduler must not preserve green liveness or readiness.
            if self.tick is None or now - self.tick > 15:
                result['process'].update(state='stale', reason='stale', live=False, ready=False)
            for key, ttl in [('migration', 180), ('webhook', 180), ('storage', 90), ('image', 90)]:
                when = result[key]['observed_at']
                if when:
                    import datetime as dt
                    age = max(0, int((dt.datetime.now(dt.timezone.utc) - schema.timestamp(when)).total_seconds()))
                    result[key]['age_seconds'] = age
                    if age > ttl: result[key].update(state='stale', reason='stale')
            if result['webhook']['state'] in {'stale', 'disabled', 'not_observed', 'unknown'}:
                result['queue']['registered'] = schema.empty_status()['queue']['registered']
            for bot in result['webhook']['bots']:
                if bot['observed_at']:
                    import datetime as dt
                    bot['age_seconds'] = max(0, int((dt.datetime.now(dt.timezone.utc)-schema.timestamp(bot['observed_at'])).total_seconds()))
                    if bot['age_seconds'] > 180: bot.update(state='stale', reason='stale')
            return result

    def loop(self):
        while not self.stop.is_set():
            try: self.collect()
            except Exception:
                # No upstream strings, paths or exceptions are logged.
                with self.lock: self.status['process'].update(state='unavailable', reason='invalid', live=False, ready=False)
            self.stop.wait(5)

    def sources_loop(self):
        from .migration import read_migrations
        from .runtime import read_runtime
        while not self.stop.is_set():
            try:
                migration = read_migrations(os.getenv('OBSERVER_MIGRATION_DIR') or None)
                runtime = read_runtime(os.getenv('OBSERVER_RUNTIME_DIR') or None)
                with self.lock:
                    if runtime[1]['instance'] != self.status['image']['instance'] or runtime[1]['state'] != 'ready':
                        self.status['webhook'] = schema.observation('webhook', 'not_observed', 'instance_changed', bots=[])
                        self.status['queue']['registered'] = schema.empty_status()['queue']['registered']
                    self.status['migration'] = migration
                    self.status['storage'], self.status['image'] = runtime
                    if migration['reason'] != 'producer_not_configured':
                        from .migration import permits_polling
                        if not permits_polling(migration):
                            self.status['webhook'] = schema.observation('webhook', 'not_observed', 'migration_pause', bots=[])
                            self.status['queue']['registered'] = schema.empty_status()['queue']['registered']
            except Exception:
                with self.lock:
                    self.status['migration'] = schema.observation('migration', 'unavailable', 'invalid', operations=[])
                    self.status['storage'] = schema.observation('runtime', 'unavailable', 'invalid', filesystems=[])
                    self.status['image'] = schema.empty_status()['image']
                    self.status['webhook'] = schema.observation('webhook', 'not_observed', 'instance_changed', bots=[])
                    self.status['queue']['registered'] = schema.empty_status()['queue']['registered']
            self.stop.wait(5)

    def webhook_loop(self):
        from .webhook import collect_webhooks
        while not self.stop.is_set():
            try:
                result = collect_webhooks(self, os.getenv('OBSERVER_REGISTRY') or None)
                with self.lock:
                    self.status['webhook'] = result
                    values = [b['pending_update_count'] for b in result['bots'] if b['pending_update_count'] is not None]
                    self.status['queue']['registered'] = dict(coverage='registered', observed_clients=len(result['bots']),
                        known_pending_clients=len(values), pending_lower_bound=sum(values) if values else None)
            except Exception:
                with self.lock: self.status['webhook'] = schema.observation('webhook', 'unavailable', 'invalid', bots=[])
            self.stop.wait(60)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    def __init__(self, address, collector):
        self.collector = collector
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request); return
        try: super().process_request(request, address)
        except Exception:
            self.slots.release(); self.shutdown_request(request)

    def process_request_thread(self, request, address):
        try: super().process_request_thread(request, address)
        finally: self.slots.release()

    def handle_error(self, request, client_address):
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = 'Observer'
    sys_version = ''
    def setup(self):
        super().setup(); self.connection.settimeout(3)
    def log_message(self, *args): pass
    def send_error(self, code, message=None, explain=None):
        self.respond(code, b'{"error":"request_rejected"}')
    def respond(self, code, body):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        if self.command != 'HEAD': self.wfile.write(body)
    def do_GET(self):
        if self.path not in {'/health/live', '/health/ready', '/status', '/selfz'}:
            self.respond(404, b'{"error":"not_found"}'); return
        if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Length', '0') != '0':
            self.respond(400, b'{"error":"request_rejected"}'); return
        try:
            c = self.server.collector
            status = c.snapshot()
            if self.path == '/status': self.respond(200, schema.serialize_status(status)); return
            if self.path == '/selfz':
                up = c.tick is not None and time.monotonic() - c.tick <= 15
            else: up = status['process']['live' if self.path.endswith('/live') else 'ready']
            self.respond(200 if up else 503, json.dumps(dict(state='ready' if up else 'unavailable', depth=status['process']['depth'])).encode('ascii'))
        except Exception: self.respond(503, b'{"error":"snapshot_unavailable"}')
    do_HEAD = do_GET
    def do_POST(self): self.respond(405, b'{"error":"method_not_allowed"}')
    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_POST


def main():
    import sys
    if '--selfcheck' in sys.argv:
        try: return 0 if probes.request('127.0.0.1', 8090, '/selfz')[0] == 200 else 1
        except Exception: return 1
    try:
        value = os.getenv('TELEGRAM_STAT') or 'false'
        if value not in {'true', 'TRUE', '1', 'false', 'FALSE', '0'}: return 1
        c = Collector(os.getenv('TELEGRAM_HTTP_IP_ADDRESS') or '0.0.0.0', os.getenv('TELEGRAM_HTTP_PORT') or '8081', value in {'true', 'TRUE', '1'})
        for fn in [c.loop, c.sources_loop, c.webhook_loop]: threading.Thread(target=fn, daemon=True).start()
        Server(('0.0.0.0', 8090), c).serve_forever(poll_interval=0.5)
    except Exception: return 1


if __name__ == '__main__':
    raise SystemExit(main())
