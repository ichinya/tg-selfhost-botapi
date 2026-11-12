"""Explicit Docker acceptance, isolated from Telegram and production state."""
import argparse
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import uuid

CHUNK = 65536
LIMIT = 2048 * 1024 * 1024
NGINX_IMAGE = "nginx:1.28.0-alpine3.21"
PYTHON_IMAGE = "python:3.13.5-alpine3.22"
LABEL = "io.tg-selfhost.gateway-acceptance"
BOUNDARY = b"issue4-synthetic-boundary"
ROOT = Path(__file__).resolve().parent.parent


def redact(value):
    """Keep raw synthetic receipts in memory; redact every persisted checkpoint."""
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?<![0-9])[0-9]{3,20}:[A-Za-z0-9_-]{6,}", "<redacted>", value)
        value = re.sub(r"(/[^\s\"'?]*)\?[^\s\"'<>]+", r"\1?<redacted>", value)
    return value


class NotRun(RuntimeError):
    pass


@contextmanager
def temporary_directory():
    # Python's Windows mode=0700 ACL handling can exclude a restricted token.
    # All contents here are synthetic; inherit the caller's temp-directory ACL.
    path = Path(tempfile.gettempdir()) / ("issue4-" + uuid.uuid4().hex)
    path.mkdir(mode=0o755 if os.name == "nt" else 0o700)
    try:
        yield str(path)
    finally:
        shutil.rmtree(path)


class Body:
    def __init__(self, path, file_bytes, total=None, extra_file=False):
        self.path = Path(path)
        self.file_bytes = file_bytes
        self.prefix = b'--' + BOUNDARY + b'\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\nsynthetic\r\n--' + BOUNDARY + b'\r\nContent-Disposition: form-data; name="document"; filename="synthetic.bin"\r\nContent-Type: application/octet-stream\r\n\r\n'
        self.middle = b'\r\n--' + BOUNDARY + b'\r\nContent-Disposition: form-data; name="padding"\r\n\r\n'
        if extra_file:
            self.middle = self.middle.replace(b'name="padding"', b'name="padding"; filename="extra.bin"')
        self.end = b'\r\n--' + BOUNDARY + b'--\r\n'
        overhead = len(self.prefix + self.middle + self.end)
        self.padding = 0 if total is None else total - file_bytes - overhead
        if self.padding < 0:
            raise ValueError("body target smaller than multipart")
        self.size = overhead + file_bytes + self.padding
        with self.path.open("wb") as stream:
            stream.truncate(file_bytes)

    def __iter__(self):
        yield self.prefix
        with self.path.open("rb") as stream:
            while data := stream.read(CHUNK):
                yield data
        yield self.middle
        left = self.padding
        while left:
            data = b"p" * min(CHUNK, left)
            yield data
            left -= len(data)
        yield self.end


def request(host, port, body, case, chunked=False, pause=0, pause_after=65536,
            throttle=0, disconnect=False, timeout=180, on_send_complete=None, method="sendDocument", case_in_path=True):
    """Read final responses concurrently so an early 413 cannot deadlock send()."""
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(timeout)
    stream = sock.makefile("rb")
    result = {"sent": 0, "started": time.monotonic(), "interim": []}
    digest = hashlib.sha256()
    def response():
        line = stream.readline(8192)
        if not line:
            return None, {}
        status = int(line.split()[1])
        headers = {}
        while line := stream.readline(8192):
            if line == b"\r\n":
                break
            key, value = line.decode().split(":", 1)
            headers[key.lower()] = value.strip()
        return status, headers
    framing = "Transfer-Encoding: chunked" if chunked else f"Content-Length: {body.size}"
    path = f"/bot12345:synthetic/{method}" + (f"/{case}" if case_in_path else "")
    headers = f"POST {path}?fixture=1 HTTP/1.1\r\nHost: fixture\r\nX-Case: {case}\r\nContent-Type: multipart/form-data; boundary={BOUNDARY.decode()}\r\n{framing}\r\nExpect: 100-continue\r\nConnection: close\r\n\r\n"
    sender = None
    done = threading.Event()
    try:
        sock.sendall(headers.encode())
        status, response_headers = response()
        if status == 100:
            result["interim"].append(status)
            def send():
                try:
                    for index, data in enumerate(body):
                        if done.is_set():
                            break
                        if result["sent"] >= pause_after and pause and "pause_started" not in result:
                            result["pause_started"] = time.monotonic()
                            if done.wait(pause):
                                break
                            result["pause_ended"] = time.monotonic()
                        payload = f"{len(data):x}\r\n".encode() + data + b"\r\n" if chunked else data
                        sock.sendall(payload)
                        digest.update(data)
                        result["sent"] += len(data)
                        if disconnect and result["sent"] > 1024 * 1024:
                            sock.shutdown(socket.SHUT_RDWR)
                            return
                        if result["sent"] == body.size:
                            if chunked:
                                sock.sendall(b"0\r\n\r\n")
                            result["send_completed"] = time.monotonic()
                            if on_send_complete:
                                on_send_complete()
                            break
                        if throttle and done.wait(throttle):
                            break
                except OSError as exc:
                    result["send_error"] = type(exc).__name__
            sender = threading.Thread(target=send, daemon=True)
            sender.start()
            status, response_headers = response()
        result["status"] = status
        size = int(response_headers.get("content-length", "0"))
        data = stream.read(min(size, 16384))
        if data.startswith(b"{"):
            result["response"] = json.loads(data)
    except OSError as exc:
        result.update(status=None, error=type(exc).__name__)
    finally:
        done.set()
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()
        stream.close()
        if sender:
            sender.join(5)
            if sender.is_alive():
                raise RuntimeError("sender failed to terminate")
    result["body_sha256"] = digest.hexdigest()
    result["elapsed"] = time.monotonic() - result["started"]
    return result


def command(args, timeout=120):
    completed = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if completed.returncode:
        raise RuntimeError(completed.stderr[-3000:] or completed.stdout[-3000:])
    return completed.stdout.strip()


def json_http(port, path, data=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("POST" if data is not None else "GET", path,
                           json.dumps(data) if data is not None else None,
                           {"Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"control HTTP {response.status}")
        return json.loads(response.read(1024 * 1024))
    finally:
        connection.close()


def final_status(report):
    expected = report.get("expected", [])
    actual = [row["name"] for row in report["scenarios"] if "name" in row]
    if expected and (len(actual) != len(set(actual)) or set(actual) != set(expected)):
        return "FAIL"
    if report.get("cleanup") == "FAIL" or any(c["status"] == "FAIL" for c in report["scenarios"]):
        return "FAIL"
    if report.get("cleanup") != "PASS":
        return "NOTRUN"
    return "PASS" if report["scenarios"] and all(c["status"] == "PASS" for c in report["scenarios"]) else "NOTRUN"


def compose_manifest(project, nginx, python, config):
    labels = {LABEL: project}
    return {"services": {
        "botapi": {"image": python, "command": ["python", "/mock.py"], "labels": labels,
                   "ports": [], "volumes": [f"{(ROOT / 'tools/gateway_upload_mock.py').as_posix()}:/mock.py:ro"]},
        "gateway": {"image": nginx, "labels": labels, "ports": ["127.0.0.1::80", "127.0.0.1::82"], "cap_add": ["SYS_PTRACE"],
                    "volumes": [f"{(ROOT / 'nginx-main.conf').as_posix()}:/etc/nginx/nginx.conf:ro", f"{Path(config).as_posix()}:/etc/nginx/conf.d/default.conf:ro", "staging:/var/cache/nginx/client_temp"]}},
        "volumes": {"staging": {"labels": labels}}, "networks": {"default": {"labels": labels}}}


class Runner:
    def __init__(self, args, report, directory):
        self.args, self.report, self.directory = args, report, Path(directory)
        self.project = report["project"]
        self.manifest = self.directory / "compose.json"
        self.config = self.directory / "nginx.conf"
        self.empty_env = self.directory / "empty.env"
        self.docker_available = False

    def compose(self, *args):
        return command(["docker", "compose", "--env-file", str(self.empty_env),
                        "-p", self.project, "-f", str(self.manifest), *args])

    def start(self):
        try:
            command(["docker", "info", "--format", "{{.ServerVersion}}"], 20)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            raise NotRun(f"Docker unavailable: {exc}") from exc
        self.docker_available = True
        self.empty_env.write_bytes(b"")
        images = {}
        for name, tag in (("nginx", self.args.nginx_image), ("python", self.args.python_image)):
            try:
                command(["docker", "pull", tag], 180)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                raise NotRun(f"registry/image prerequisite unavailable: {exc}") from exc
            meta = json.loads(command(["docker", "image", "inspect", tag]))[0]
            images[name] = meta["Id"]
            self.report.setdefault("images", {})[name] = {"reference": tag, "id": meta["Id"],
                                                         "digests": meta.get("RepoDigests", []),
                                                         "architecture": meta.get("Architecture")}
        self.config.write_bytes((ROOT / "nginx.conf").read_bytes())
        self.report["fixture_cap_add"] = ["SYS_PTRACE"]
        self.manifest.write_text(json.dumps(compose_manifest(self.project, images["nginx"], images["python"], self.config)), encoding="utf-8")
        self.compose("config", "--quiet")
        self.compose("up", "-d")
        self.gateway = self.compose("ps", "-q", "gateway")
        self.mock = self.compose("ps", "-q", "botapi")
        self.record_resources()
        self.refresh_ports()
        deadline = time.monotonic() + 30
        while True:
            try:
                self.receipts()
                break
            except (OSError, RuntimeError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("mock readiness deadline")
                time.sleep(0.2)
        self.report["nginx_version"] = self.compose("exec", "-T", "gateway", "sh", "-c", "nginx -v 2>&1")
        self.compose("exec", "-T", "gateway", "nginx", "-t")
        self.ready()
        self.report["effective_config"] = self.compose("exec", "-T", "gateway", "nginx", "-T")
        self.report["effective_config_sha256"] = hashlib.sha256(self.report["effective_config"].encode()).hexdigest()
        import re
        for directive, value in {"client_max_body_size": "2048m", "client_body_timeout": "300s",
                                 "client_body_temp_path": "/var/cache/nginx/client_temp",
                                 "proxy_request_buffering": "on", "proxy_connect_timeout": "5s",
                                 "proxy_send_timeout": "300s", "proxy_read_timeout": "600s"}.items():
            assert re.search(r"\b" + directive + r"\s+" + re.escape(value) + r"\s*;", self.report["effective_config"]), directive

    def configure(self, **overrides):
        import re
        text = (ROOT / "nginx.conf").read_text(encoding="utf-8")
        for key, value in overrides.items():
            text, count = re.subn(r"\b" + key + r"\s+[^;]+;", f"{key} {value};", text)
            if count < 1:
                raise AssertionError(f"directive {key}: {count}")
        self.config.write_text(text, encoding="utf-8", newline="\n")
        self.compose("up", "-d", "--no-deps", "--force-recreate", "gateway")
        self.gateway = self.compose("ps", "-q", "gateway")
        self.record_resources()
        self.refresh_ports()
        self.compose("exec", "-T", "gateway", "nginx", "-t")
        self.ready()
        effective = self.compose("exec", "-T", "gateway", "nginx", "-T")
        self.report.setdefault("configs", []).append({"overrides": overrides,
                                                    "shipped": not overrides,
                                                    "sha256": hashlib.sha256(self.config.read_bytes()).hexdigest(),
                                                    "effective_sha256": hashlib.sha256(effective.encode()).hexdigest()})

    def record_resources(self):
        resources = {}
        for kind, listing in (("containers", ["ps", "-aq"]), ("networks", ["network", "ls", "-q"]),
                              ("volumes", ["volume", "ls", "-q"])):
            resources[kind] = command(["docker", *listing, "--filter", f"label={LABEL}={self.project}"]).split()
        self.report["resources"] = resources
        self.checkpoint()

    def refresh_ports(self):
        self.public_port = int(self.compose("port", "gateway", "80").rsplit(":", 1)[1])
        self.port = int(self.compose("port", "gateway", "82").rsplit(":", 1)[1])

    def ready(self):
        def check():
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
            try:
                connection.request("GET", "/synthetic-readiness")
                response = connection.getresponse()
                response.read(1024)
                return response.status == 200
            except OSError:
                return False
            finally:
                connection.close()
        wait_for(check, timeout=20)

    def case(self, name, function):
        row = next(row for row in self.report["scenarios"] if row["name"] == name)
        started = time.monotonic()
        row["started"] = started
        self.checkpoint()
        self.current_evidence = {}
        try:
            row["evidence"] = function() or {}
            row["status"] = "PASS"
        except NotRun as exc:
            row.update(status="NOTRUN", reason=str(exc))
        except Exception as exc:
            row.update(status="FAIL", reason=f"{type(exc).__name__}: {exc}")
            row["evidence"] = getattr(self, "current_evidence", {})
        try:
            (self.directory / "source.bin").unlink(missing_ok=True)
        except OSError as exc:
            row.update(status="FAIL", reason=f"input cleanup: {exc}")
        if row["status"] == "PASS":
            try:
                row["staging_after"] = self.await_clean({"free": 0})
            except NotRun as exc:
                row.update(status="NOTRUN", reason=f"post-scenario staging cleanup: {exc}")
            except Exception as exc:
                row.update(status="FAIL", reason=f"post-scenario staging cleanup: {exc}")
        row["elapsed"] = time.monotonic() - started
        self.checkpoint()

    def checkpoint(self):
        if self.args is not None:
            self.report["status"] = final_status(self.report)
            self.args.report.write_text(json.dumps(redact(self.report), indent=2), encoding="utf-8")

    def upload(self, name, size=4 * 1024 * 1024, total=None, chunked=False, expected=200, extra_file=False, **options):
        body = Body(self.directory / "source.bin", size, total, extra_file=extra_file)
        result = request("127.0.0.1", self.port, body, name, chunked=chunked, **options)
        receipt = self.receipts().get(name)
        if expected == 200 and result.get("status") == 200:
            receipt = wait_for(lambda: (r if (r := self.receipts().get(name, {})).get("response_sent") else None), timeout=5)
        evidence = {"request_bytes": body.size, "file_bytes": size, "client": result, "receipt": receipt,
                    "config_sha256": hashlib.sha256(self.config.read_bytes()).hexdigest()}
        self.current_evidence = evidence
        assert result["status"] == expected, evidence
        if expected == 200:
            assert receipt and receipt.get("body_received"), evidence
            assert receipt["body_bytes"] == body.size == result["sent"], evidence
            assert receipt["body_sha256"] == result["body_sha256"], evidence
            assert result["response"]["body_sha256"] == receipt["body_sha256"], evidence
            assert receipt["parts"][0]["sha256"] == hashlib.sha256(b"synthetic").hexdigest(), evidence
            assert receipt["parts"][2]["bytes"] == body.padding, evidence
            if extra_file:
                assert 'filename="extra.bin"' in receipt["parts"][2]["headers"], evidence
            file_part = receipt["parts"][1]
            digest = hashlib.sha256()
            with body.path.open("rb") as stream:
                while data := stream.read(CHUNK):
                    digest.update(data)
            assert (file_part["bytes"], file_part["sha256"]) == (size, digest.hexdigest()), evidence
        elif expected == 413:
            assert receipt is None, evidence
        return evidence

    def cleanup(self):
        if not self.docker_available:
            self.report.update(cleanup="PASS", cleanup_note="no daemon access; no resources created")
            return
        errors = []
        # Inventory by exact owner label also catches half-created Compose resources.
        for resource, lsargs, rmargs in (("container", ["ps", "-aq"], ["rm", "-f"]),
                                         ("network", ["network", "ls", "-q"], ["network", "rm"]),
                                         ("volume", ["volume", "ls", "-q"], ["volume", "rm"])):
            try:
                ids = command(["docker", *lsargs, "--filter", f"label={LABEL}={self.project}"]).split()
                if ids:
                    command(["docker", *rmargs, *ids])
            except Exception as exc:
                errors.append(f"{resource}: {exc}")
        self.report["cleanup"] = "FAIL" if errors else "PASS"
        self.report["cleanup_errors"] = errors

    def receipts(self):
        return self.control_request("/__receipts")

    def control(self, name, **options):
        self.control_request("/__control", {"case": name, **options})

    def control_request(self, path, data=None):
        # The mock publishes no host port. Its synthetic administration channel
        # runs inside the exact fixture container and is separate from uploads.
        script = ("import http.client,json,sys; "
                  "c=http.client.HTTPConnection('127.0.0.1',8081,timeout=5); "
                  "c.request(sys.argv[1],sys.argv[2],None if sys.argv[3]=='null' else sys.argv[3],"
                  "{'Content-Type':'application/json'}); r=c.getresponse(); "
                  "assert r.status==200,r.status; sys.stdout.write(r.read(1048576).decode()); c.close()")
        return json.loads(self.compose("exec", "-T", "botapi", "python", "-c", script,
                                       "POST" if data is not None else "GET", path, json.dumps(data)))

    def snapshot(self, stopped=False):
        script = r'''df -Pk /var/cache/nginx/client_temp
find /var/cache/nginx/client_temp -type f -exec stat -c 'file:%i:%s:%b' {} \;
for p in /proc/[0-9]*; do
  for f in "$p"/fd/*; do
    target=$(readlink "$f" 2>/dev/null) || { echo fdskip; continue; }
    case "$target" in /var/cache/nginx/client_temp/*)
      stat -L -c 'fd:%i:%s:%b' "$f" 2>/dev/null || echo fdskip;;
    esac
  done
done
'''
        output = self.compose(*(["run", "--rm", "--no-deps", "gateway"] if stopped else ["exec", "-T", "gateway"]), "sh", "-c", script)
        inodes, files, descriptors, skipped, free = {}, 0, 0, 0, None
        for line in output.splitlines():
            if line.startswith(("file:", "fd:")):
                kind, inode, size, blocks = line.split(":")
                inodes[inode] = {"bytes": int(size), "blocks": int(blocks) * 512}
                files += kind == "file"
                descriptors += kind == "fd"
            elif line == "fdskip":
                skipped += 1
            elif len(line.split()) >= 6 and line.split()[0] != "Filesystem":
                try:
                    free = int(line.split()[3]) * 1024
                except ValueError:
                    pass
        if free is None:
            raise RuntimeError("missing df evidence")
        return {"free": free, "files": files, "fds": descriptors, "fds_skipped": skipped,
                "bytes": sum(item["bytes"] for item in inodes.values()),
                "blocks": sum(item["blocks"] for item in inodes.values())}

    def await_clean(self, before):
        deadline = time.monotonic() + 15
        while True:
            after = self.snapshot()
            if after["fds_skipped"]:
                raise NotRun(f"worker fd observation unavailable: {after}")
            if after["files"] == after["fds"] == after["blocks"] == 0 and after["free"] >= before["free"] - 1024 * 1024:
                return after
            if time.monotonic() >= deadline:
                raise AssertionError({"before": before, "after": after, "reason": "staging not reclaimed"})
            time.sleep(0.25)

    def fd_observation_probe(self):
        script = r'''pidfile=$(mktemp)
chmod 666 "$pidfile"
trap '[ -s "$pidfile" ] && kill "$(cat "$pidfile")" 2>/dev/null; kill "$launcher" 2>/dev/null; wait "$launcher" 2>/dev/null; rm -f "$pidfile"' EXIT
su -s /bin/sh nginx -c 'echo $$ > "$1"; exec sleep 30' sh "$pidfile" &
launcher=$!
i=0
while [ ! -s "$pidfile" ] && [ "$i" -lt 50 ]; do sleep 0.1; i=$((i+1)); done
[ -s "$pidfile" ] || exit 1
pid=$(cat "$pidfile")
readlink "/proc/$pid/fd/0" 2>/dev/null >/dev/null
'''
        try:
            self.compose("exec", "-T", "gateway", "sh", "-c", script)
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            raise NotRun("worker fd observation unavailable") from exc
        return {"worker_fd_observation": "available"}

    def worker_probe(self):
        output = self.compose("exec", "-T", "gateway", "sh", "-c",
                              "id nginx; stat -c '%u:%g:%a' /var/cache/nginx/client_temp; "
                              "su -s /bin/sh nginx -c 'touch /var/cache/nginx/client_temp/probe && rm /var/cache/nginx/client_temp/probe'")
        return {"identity_permissions": output}


class AsyncCall:
    def __init__(self, function):
        self.result = None
        self.error = None
        def run():
            try:
                self.result = function()
            except BaseException as exc:
                self.error = exc
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def finish(self, timeout=200):
        self.thread.join(timeout)
        if self.thread.is_alive():
            raise RuntimeError("scenario watchdog expired")
        if self.error:
            raise self.error
        return self.result


def wait_for(function, timeout=20):
    deadline = time.monotonic() + timeout
    while True:
        value = function()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError("observation deadline expired")
        time.sleep(0.25)


def upstream_queue(runner):
    text = runner.compose("exec", "-T", "gateway", "cat", "/proc/net/tcp")
    return sum(int(fields[4].split(":")[0], 16) for line in text.splitlines()[1:]
               if len(fields := line.split()) > 4 and fields[2].endswith(":1F91") and fields[3] == "01")


def backpressure(runner, name, chunked, negative=False):
    runner.control(name, read_pause=6 if negative else 75)
    sent = threading.Event()
    call = AsyncCall(lambda: runner.upload(name, size=64 * 1024 * 1024, chunked=chunked,
                                           expected=504 if negative else 200, on_send_complete=sent.set))
    observations = []
    try:
        receipt = wait_for(lambda: runner.receipts().get(name, {}).get("stall_started"))
        observed = time.monotonic()
        assert sent.is_set(), "upstream started before client completed buffered body"
        first = wait_for(lambda: upstream_queue(runner), timeout=5)
        if not negative:
            time.sleep(3)
        second = upstream_queue(runner) if not negative else first
        observations = [{"at": receipt, "queue": first}, {"at": time.monotonic(), "queue": second}]
        result = call.finish()
        result["backpressure"] = observations
        runner.current_evidence = result
        assert first > 0 and second > 0, result
        receipt = runner.receipts()[name]
        if negative:
            assert not receipt.get("body_received"), receipt
            assert 0 <= time.monotonic() - observed < 30, receipt
        else:
            assert receipt["resumed"] - receipt["stall_started"] >= 74, receipt
        return result
    finally:
        if call.thread.is_alive():
            call.finish()


def idle_client(runner, name, chunked):
    body = Body(runner.directory / "source.bin", 4 * 1024 * 1024)
    before = command(["docker", "logs", runner.gateway])
    result = request("127.0.0.1", runner.port, body, name, chunked=chunked, pause=5)
    # This request is isolated; the privacy log deliberately omits its URI.
    logs = command(["docker", "logs", runner.gateway])
    assert logs.startswith(before), "gateway logs changed unexpectedly"
    evidence = {"client": result, "access_408": any(line.startswith("POST api 408 ") for line in logs[len(before):].splitlines())}
    runner.current_evidence = evidence
    assert result["status"] in (None, 408) and evidence["access_408"], evidence
    assert name not in runner.receipts(), evidence
    phase = result["started"] + result["elapsed"] - result.get("pause_started", result["started"])
    evidence["client_idle_phase_seconds"] = phase
    assert 1 <= phase < 10, evidence
    return evidence


def slow_cases():
    return [f"{kind}-{framing}" for framing in ("length", "chunked")
            for kind in ("progress70", "client70", "response70", "send70", "client2", "read2", "send2")]


def run_slow(runner):
    for framing in ("length", "chunked"):
        chunked = framing == "chunked"
        runner.configure()
        name = "progress70-" + framing
        def progress(n=name, c=chunked):
            result = runner.upload(n, size=8 * 1024 * 1024, chunked=c, throttle=0.56)
            assert result["client"]["send_completed"] - result["client"]["started"] > 70, result
            return result
        runner.case(name, progress)
        name = "client70-" + framing
        def paused(n=name, c=chunked):
            result = runner.upload(n, chunked=c, pause=75)
            assert result["client"]["pause_ended"] - result["client"]["pause_started"] >= 74, result
            return result
        runner.case(name, paused)
        name = "response70-" + framing
        runner.control(name, response_pause=75)
        def response(n=name, c=chunked):
            result = runner.upload(n, chunked=c)
            # Client and receipt clocks are intentionally never subtracted.
            receipt = runner.receipts()[n]
            assert receipt["response_sent"] - receipt["body_received"] >= 74, receipt
            return result
        runner.case(name, response)
        name = "send70-" + framing
        runner.case(name, lambda n=name, c=chunked: backpressure(runner, n, c))
        runner.configure(client_body_timeout="2s")
        name = "client2-" + framing
        runner.case(name, lambda n=name, c=chunked: idle_client(runner, n, c))
        runner.configure(proxy_read_timeout="2s")
        name = "read2-" + framing
        runner.control(name, response_pause=6)
        def read_timeout(n=name, c=chunked):
            result = runner.upload(n, chunked=c, expected=504)
            receipt = runner.receipts()[n]
            assert receipt.get("body_received") and not receipt.get("response_sent"), receipt
            client = result["client"]
            phase = client["started"] + client["elapsed"] - client["send_completed"]
            result["read_idle_phase_seconds"] = phase
            assert 1 <= phase < 15, result
            return result
        runner.case(name, read_timeout)
        runner.configure(proxy_send_timeout="2s")
        name = "send2-" + framing
        runner.case(name, lambda n=name, c=chunked: backpressure(runner, n, c, negative=True))
    runner.configure()


def staging(runner, name, kind, chunked=False):
    before = runner.snapshot()
    runner.current_evidence = {"before": before}
    if kind in ("success", "crash"):
        call = AsyncCall(lambda: request("127.0.0.1", runner.port, Body(runner.directory / "source.bin", 8 * 1024 * 1024),
                                         name, chunked=chunked, pause=8, pause_after=2 * 1024 * 1024))
        try:
            last = None
            def observe_growth():
                nonlocal last
                last = runner.snapshot()
                return last if last["bytes"] >= 1024 * 1024 else None
            try:
                during = wait_for(observe_growth, timeout=6)
            except AssertionError as exc:
                if last and last["fds_skipped"]:
                    raise NotRun(f"worker fd observation unavailable: {last}") from exc
                raise
            assert during["blocks"] > 0 and name not in runner.receipts(), during
            if kind == "crash":
                command(["docker", "kill", "--signal", "KILL", runner.gateway])
                result = call.finish()
                assert result.get("status") != 200, result
                orphan = runner.snapshot(stopped=True)
                # All traffic in this disposable project is stopped. Clear this
                # project's staging only, including orphans left by SIGKILL.
                runner.compose("run", "--rm", "--no-deps", "gateway", "find", "/var/cache/nginx/client_temp", "-type", "f", "-delete")
                runner.compose("start", "gateway")
                runner.refresh_ports()
                runner.ready()
                result["orphan"] = orphan
            else:
                result = call.finish()
                receipt = runner.receipts().get(name)
                assert result["status"] == 200 and receipt and receipt["body_sha256"] == result["body_sha256"], result
        finally:
            if call.thread.is_alive():
                call.finish()
    elif kind == "overflow":
        during = None
        result = runner.upload(name, size=1024 * 1024, total=8 * 1024 * 1024 + 1, chunked=chunked, expected=413)
    elif kind == "timeout":
        during = None
        result = idle_client(runner, name, chunked)
    elif kind == "upstream5xx":
        during = None
        runner.control(name, status=503)
        result = runner.upload(name, chunked=chunked, expected=503)
        assert runner.receipts().get(name, {}).get("body_received"), result
    else:
        during = None
        body = Body(runner.directory / "source.bin", 8 * 1024 * 1024)
        result = request("127.0.0.1", runner.port, body, name, chunked=chunked, disconnect=True)
        assert result["status"] != 200 and name not in runner.receipts(), result
    after = runner.await_clean(before)
    recovery = runner.upload(name + "-recovery", size=1024)
    return {"before": before, "during": during, "result": result, "after": after, "recovery": recovery}


def disk_full(runner):
    manifest = json.loads(runner.manifest.read_text(encoding="utf-8"))
    normal = json.loads(json.dumps(manifest))
    manifest["volumes"]["fault"] = {"labels": {LABEL: runner.project}, "driver": "local",
                                         "driver_opts": {"type": "tmpfs", "device": "tmpfs", "o": "size=2097152"}}
    replace_spool_volume(manifest, "storage_checks", "fault")
    try:
        runner.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        try:
            runner.configure()
        except RuntimeError as exc:
            raise NotRun(f"bounded filesystem fixture unavailable: {exc}") from exc
        before = runner.snapshot()
        assert before["free"] <= 2097152, {"reason": "fault fixture is not capacity bounded", "snapshot": before}
        body = Body(runner.directory / "source.bin", 8 * 1024 * 1024)
        result = request("127.0.0.1", runner.port, body, "disk-full", chunked=True)
        assert result["status"] not in (None, 200) and "disk-full" not in runner.receipts(), result
        after = runner.await_clean(before)
        recovery = runner.upload("disk-full-recovery", size=1024)
        return {"fixture_bytes": 2097152, "client": result, "after": after, "recovery": recovery}
    finally:
        runner.manifest.write_text(json.dumps(normal), encoding="utf-8")
        runner.configure()


def storage_cases():
    return ["capacity-storage", "worker-fresh", "worker-reused", "disk-full", "certificate", "log-privacy"] + [
        f"storage-{kind}-{framing}" for framing in ("length", "chunked")
        for kind in ("success", "overflow", "timeout", "disconnect", "upstream5xx", "crash")]


def replace_spool_volume(manifest, old, new):
    volumes = manifest["services"]["gateway"]["volumes"]
    spool = f"{old}:/var/cache/nginx/client_temp"
    if volumes.count(spool) != 1:
        raise AssertionError("expected exactly one spool mount")
    volumes[volumes.index(spool)] = f"{new}:/var/cache/nginx/client_temp"


def use_storage_volume(manifest, project):
    manifest["volumes"]["storage_checks"] = {"labels": {LABEL: project}}
    replace_spool_volume(manifest, "staging", "storage_checks")


def run_storage(runner):
    def disk():
        probe = runner.fd_observation_probe()
        snapshot = runner.snapshot()
        snapshot.update(probe)
        if snapshot["free"] < 256 * 1024 * 1024 or shutil.disk_usage(runner.directory).free < 256 * 1024 * 1024:
            raise NotRun("storage requires 256 MiB free on host and volume backing")
        return snapshot
    runner.case("capacity-storage", disk)
    if next(row for row in runner.report["scenarios"] if row["name"] == "capacity-storage")["status"] != "PASS":
        return
    manifest = json.loads(runner.manifest.read_text(encoding="utf-8"))
    use_storage_volume(manifest, runner.project)
    runner.manifest.write_text(json.dumps(manifest), encoding="utf-8")
    runner.configure()
    runner.case("worker-fresh", runner.worker_probe)
    runner.configure()
    runner.case("worker-reused", runner.worker_probe)
    for framing in ("length", "chunked"):
        for kind in ("success", "overflow", "timeout", "disconnect", "upstream5xx", "crash"):
            runner.configure(**({"client_max_body_size": "8m"} if kind == "overflow" else
                               {"client_body_timeout": "2s"} if kind == "timeout" else {}))
            name = f"storage-{kind}-{framing}"
            runner.case(name, lambda n=name, k=kind, c=framing == "chunked": staging(runner, n, k, c))
    runner.configure()
    runner.case("disk-full", lambda: disk_full(runner))
    runner.case("certificate", lambda: certificate_upload(runner))
    runner.case("log-privacy", lambda: log_privacy(runner))


def certificate_upload(runner):
    certificate = runner.directory / "public.pem"
    key = runner.directory / "synthetic-key.pem"
    try:
        try:
            command(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                     "-subj", "/CN=synthetic.invalid", "-keyout", str(key), "-out", str(certificate)], 30)
        except OSError as exc:
            raise NotRun("openssl required for synthetic public certificate") from exc
        pem = certificate.read_bytes()
    finally:
        key.unlink(missing_ok=True)
    assert b"BEGIN CERTIFICATE" in pem and b"PRIVATE KEY" not in pem
    prefix = b'--' + BOUNDARY + b'\r\nContent-Disposition: form-data; name="url"\r\n\r\nhttps://synthetic.invalid/webhook\r\n--' + BOUNDARY + b'\r\nContent-Disposition: form-data; name="certificate"; filename="public.pem"\r\nContent-Type: application/x-pem-file\r\n\r\n'
    data = prefix + pem + b'\r\n--' + BOUNDARY + b'--\r\n'
    assert len(data) < 256 * 1024
    class SmallBody:
        size = len(data)
        def __iter__(self):
            yield data
    result = request("127.0.0.1", runner.port, SmallBody(), "certificate", method="setWebhook", case_in_path=False)
    receipt = runner.receipts().get("certificate")
    evidence = {"client": result, "receipt": receipt}
    runner.current_evidence = evidence
    assert result["status"] == 200 and receipt, evidence
    assert receipt["uri"] == "/bot12345:synthetic/setWebhook?fixture=1", evidence
    assert receipt["parts"][0]["sha256"] == hashlib.sha256(b"https://synthetic.invalid/webhook").hexdigest(), evidence
    assert receipt["parts"][1]["sha256"] == hashlib.sha256(pem).hexdigest(), evidence
    assert receipt["body_sha256"] == result["body_sha256"], evidence
    return evidence


def log_privacy(runner):
    before = command(["docker", "logs", runner.gateway])
    runner.upload("log-privacy-probe", size=1024)
    logs = command(["docker", "logs", runner.gateway])
    assert logs.startswith(before), "gateway logs changed unexpectedly"
    logs = logs[len(before):]
    assert "12345:synthetic" not in logs and "fixture=1" not in logs and "?x=" not in logs
    assert any(line.startswith("POST api 200 ") for line in logs.splitlines())
    assert "log-privacy-probe" not in logs
    return {"token_redacted": True, "query_omitted": True,
            "logs_sha256": hashlib.sha256(logs.encode()).hexdigest()}


def size_cases(limit):
    return [(f"{framing}-{delta:+d}", framing == "chunked", limit + delta)
            for framing in ("length", "chunked") for delta in (-1, 0, 1)]


def inventory(profile):
    if profile == "quick":
        profile = "fast"
    groups = {
        "fast": ["smoke", "file-4m", "routing", "legacy-413"] + ["small-" + c[0] for c in size_cases(8 * 1024 * 1024)],
        "full": ["capacity-full", "file-2000m"] + ["full-" + c[0] for c in size_cases(LIMIT)],
        "slow": slow_cases(), "storage": storage_cases()}
    return [name for group in (groups.values() if profile == "all" else [groups[profile]]) for name in group]


def capacity(runner):
    required = max(10 * 1024 ** 3, 3 * LIMIT + 2 * 1024 ** 3)
    host = shutil.disk_usage(runner.directory).free
    output = runner.compose("exec", "-T", "gateway", "df", "-Pk", "/var/cache/nginx/client_temp")
    docker = int(output.splitlines()[-1].split()[3]) * 1024
    evidence = {"required": required, "host_free": host, "docker_free": docker}
    runner.current_evidence = evidence
    if host < required or docker < required:
        raise NotRun(f"insufficient host/Docker backing capacity: {evidence}")
    return evidence


def routing(runner):
    connection = http.client.HTTPConnection("127.0.0.1", runner.port, timeout=10)
    evidence = []
    try:
        for method, uri, data, content in (("GET", "/file/bot12345:synthetic/path.bin?x=%2F", None, "application/json"),
                                           ("POST", "/bot12345:synthetic/getMe?x=%2F", b'{"test":true}', "application/json"),
                                           ("POST", "/bot12345:synthetic/getWebhookInfo?x=1", b"field=value", "application/x-www-form-urlencoded")):
            case = "routing-" + content
            connection.request(method, uri, data, {"Content-Type": content, "X-Case": case})
            response = connection.getresponse()
            body = response.read()
            if data is None:
                assert response.status == 404, response.status
                assert case not in runner.receipts(), "blocked file request reached upstream"
            else:
                result = json.loads(body)
                assert response.status == 200, result
                receipt = runner.receipts()[case]
                assert receipt["uri"] == uri and receipt["body_sha256"] == hashlib.sha256(data).hexdigest(), receipt
            evidence.append({"uri": uri, "status": response.status})
    finally:
        connection.close()
    return {"requests": evidence}


def run_profiles(runner, profile):
    if profile == "quick":
        profile = "fast"
    if profile in ("fast", "all"):
        runner.case("smoke", lambda: runner.upload("smoke", size=2 * 1024 * 1024))
        runner.case("file-4m", lambda: runner.upload("file-4m"))
        runner.case("routing", lambda: routing(runner))
        runner.configure(client_max_body_size="1m")
        runner.case("legacy-413", lambda: runner.upload("legacy-413", expected=413))
        runner.configure(client_max_body_size="8m")
        for suffix, chunked, total in size_cases(8 * 1024 * 1024):
            name = "small-" + suffix
            runner.case(name, lambda n=name, c=chunked, t=total: runner.upload(n, total=t, chunked=c,
                                                                          extra_file=True, expected=413 if t > 8 * 1024 * 1024 else 200))
        runner.configure()
    if profile in ("full", "all"):
        runner.case("capacity-full", lambda: capacity(runner))
        if next(row for row in runner.report["scenarios"] if row["name"] == "capacity-full")["status"] == "PASS":
            runner.configure()
            runner.case("file-2000m", lambda: runner.upload("file-2000m", size=2000 * 1024 * 1024, timeout=1200))
            for suffix, chunked, total in size_cases(LIMIT):
                name = "full-" + suffix
                runner.case(name, lambda n=name, c=chunked, t=total: runner.upload(n, total=t, chunked=c, expected=413 if t > LIMIT else 200, timeout=1200))
    if profile in ("slow", "all"):
        run_slow(runner)
    if profile in ("storage", "all"):
        run_storage(runner)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["quick", "fast", "slow", "full", "storage", "all"], default="quick")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--project", default="issue4-" + uuid.uuid4().hex[:16])
    parser.add_argument("--nginx-image", default=os.environ.get("GATEWAY_NGINX_IMAGE", NGINX_IMAGE))
    parser.add_argument("--python-image", default=os.environ.get("GATEWAY_PYTHON_IMAGE", PYTHON_IMAGE))
    parser.add_argument("--deadline", type=int, default=2700, help="total run watchdog in seconds")
    args = parser.parse_args(argv)
    if args.deadline <= 0:
        parser.error("deadline must be positive")
    if not args.project.startswith("issue4-") or not all(c.isalnum() or c == "-" for c in args.project):
        parser.error("project must use issue4- prefix and alphanumeric/hyphen characters")
    report = {"schema": 1, "revision": args.revision, "profile": args.profile, "project": args.project,
              "config_sha256": hashlib.sha256((ROOT / "nginx.conf").read_bytes()).hexdigest(),
              "expected": inventory(args.profile),
              "scenarios": [{"name": name, "status": "NOTRUN"} for name in inventory(args.profile)], "cleanup": "NOTRUN"}
    report["harness_sha256"] = {name: hashlib.sha256((ROOT / "tools" / name).read_bytes()).hexdigest()
                                for name in ("check_gateway_uploads.py", "gateway_upload_mock.py")}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    def save():
        report["status"] = final_status(report)
        args.report.write_text(json.dumps(redact(report), indent=2), encoding="utf-8")
    save()
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"signal {signum}")
    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, interrupted)
    if hasattr(signal, "SIGALRM"):
        previous[signal.SIGALRM] = signal.signal(signal.SIGALRM, interrupted)
        signal.alarm(args.deadline)
        watchdog = None
    else:
        import _thread
        watchdog = threading.Timer(args.deadline, _thread.interrupt_main)
        watchdog.daemon = True
        watchdog.start()
    manager = temporary_directory()
    try:
        directory = manager.__enter__()
        runner = Runner(args, report, directory)
        try:
            runner.start()
            run_profiles(runner, args.profile)
        except (KeyboardInterrupt, Exception) as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"
            if not isinstance(exc, NotRun):
                report["scenarios"].append({"name": "runner", "status": "FAIL", "reason": str(exc)})
        finally:
            if watchdog is not None:
                watchdog.cancel()
            elif hasattr(signal, "SIGALRM"):
                signal.alarm(0)
            runner.cleanup()
    finally:
        if watchdog is not None:
            watchdog.cancel()
        elif hasattr(signal, "SIGALRM"):
            signal.alarm(0)
        try:
            manager.__exit__(None, None, None)
        except Exception as exc:
            report.update(cleanup="FAIL", temp_cleanup_error=str(exc))
        save()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    print(json.dumps({"status": report["status"], "report": str(args.report)}))
    return 0 if report["status"] == "PASS" else 2 if report["status"] == "NOTRUN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
