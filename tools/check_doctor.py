#!/usr/bin/env python3
"""Explicit isolated Docker integration. Never runs during unittest discovery."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid

import doctor
from doctor_runtime import Runner, Budget, RunError, endpoint, STORAGE_METADATA, WRITE_PROBE, TRANSFER_METADATA, TARGET_DESTINATION

FIXTURES = Path(__file__).resolve().parent / "doctor_fixtures"
SECRET = "synthetic-doctor-credential"


def assert_report(result, code):
    if result["exit_code"] != code or result["schema_version"] != 1:
        raise AssertionError("report/exit mismatch")
    verdict = {0: "READY", 1: "BLOCKED", 2: "UNKNOWN", 3: "UNKNOWN"}[code]
    if result["readiness"]["verdict"] != verdict:
        raise AssertionError("report/verdict mismatch")
    if code == 0 and any(c["required"] and c["status"] != "PASS" for c in result["checks"]):
        raise AssertionError("READY with incomplete evidence")
    if SECRET in json.dumps(result):
        raise AssertionError("credential escaped report")


class RecordingRunner(Runner):
    def __init__(self):
        super().__init__(budget=Budget(5, 90))
        self.calls = []

    def run(self, argv):
        self.calls.append(list(argv))
        return super().run(argv)


def assert_commands(calls):
    for argv in calls:
        if argv[0] == "docker":
            if len(argv) < 2 or argv[1] not in {"compose", "info", "context", "ps", "inspect", "image", "exec"}:
                raise AssertionError("doctor attempted a Docker mutation")
            if argv[1] == "compose" and argv[-3:] != ["config", "--format", "json"]:
                raise AssertionError("doctor attempted a Compose mutation")
            if argv[1] == "image" and argv[2] != "inspect":
                raise AssertionError("doctor attempted an image mutation")
            if argv[1] == "exec":
                position = 2
                if argv[position] == "--user":
                    position += 2
                program = argv[position + 1:]
                if program and program[0] == "timeout":
                    program = program[6:]
                scripts = {STORAGE_METADATA, WRITE_PROBE, TRANSFER_METADATA, TARGET_DESTINATION,
                           'test -f "$1" && test -r "$1" && test -s "$1"',
                           'readlink /proc/1/exe; cat /proc/1/status; printf "\\nDOCTOR_ARGV\\n"; cat /proc/1/cmdline',
                           'nginx -T 2>/dev/null', 'nginx -v 2>&1'}
                if program != ["telegram-bot-api", "--version"] and not (len(program) >= 3 and program[:2] == ["sh", "-c"] and program[2] in scripts):
                    raise AssertionError("unexpected container program")
        elif len(argv) < 3 or Path(argv[1]).name != "doctor_runtime.py" or argv[2] != "--http-worker":
            raise AssertionError("unexpected doctor subprocess")
        for value in argv:
            if value.startswith(("http://", "https://")):
                try:
                    parsed = endpoint(value)
                    if parsed.path not in {"", "/"} or "telegram.org" in parsed.hostname.lower():
                        raise ValueError
                except ValueError:
                    raise AssertionError("forbidden HTTP request") from None


def run_case(argv):
    runner = RecordingRunner()
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = doctor.main(argv, runner=runner)
    result = json.loads(out.getvalue())
    assert_report(result, code)
    assert_commands(runner.calls)
    if SECRET in out.getvalue() + err.getvalue() or err.getvalue():
        raise AssertionError("unexpected diagnostic output")
    return result, code


class Harness:
    def __init__(self):
        self.project = "doctor-" + uuid.uuid4().hex[:12]
        self.compose = ["docker", "compose", "-p", self.project, "-f", str(FIXTURES / "compose.yml")]
        self.runner = Runner(timeout=240, deadline=1200, max_output=16 * 1024 * 1024)
        self.bases = {}
        self.built = False

    def command(self, argv):
        code, output = self.runner.run(argv)
        if code:
            raise RunError("integration_command_failed")
        return output

    def pin(self, reference):
        if not re.fullmatch(r"[a-z0-9./:_-]+(?:@sha256:[a-f0-9]{64})?", reference):
            raise ValueError("invalid fixture base")
        self.command(["docker", "pull", reference])
        image = json.loads(self.command(["docker", "image", "inspect", reference]))[0]
        digests = image.get("RepoDigests") or []
        if not digests:
            raise RunError("fixture_digest_missing")
        return digests[0]

    def snapshot(self):
        raw = self.command(self.compose + ["exec", "-T", "botapi", "sh", "-c",
            'sha256sum /var/lib/telegram-bot-api/sentinel; find /var/lib/telegram-bot-api /tmp/telegram-bot-api -name ".doctor-*"'])
        if b".doctor-" in raw:
            raise AssertionError("probe leaked")
        return raw

    def stop(self):
        # Cleanup is independent of the exhausted diagnostic/harness budget.
        try:
            subprocess.run(self.compose + ["down", "--volumes", "--remove-orphans"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=60, check=True)
            if self.built:
                subprocess.run(["docker", "image", "rm", self.project + ":synthetic", self.project + ':observer'],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=30, check=True)
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("synthetic project cleanup failed") from None

    def run(self):
        self.command(["docker", "version", "--format", "{{.Server.Version}}"])
        cases = []
        env_keys = ("DOCTOR_FIXTURE_IMAGE", "DOCTOR_PYTHON_IMAGE", "DOCTOR_NGINX_IMAGE", 'DOCTOR_OBSERVER_IMAGE')
        previous = {k: os.environ.get(k) for k in env_keys}
        signals = {}
        for signum in (signal.SIGINT, signal.SIGTERM):
            signals[signum] = signal.signal(signum, lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
        try:
            self.bases = {"python": self.pin(os.environ.get("DOCTOR_PYTHON_IMAGE", "python:3.13.5-alpine3.22")),
                          "nginx": self.pin(os.environ.get("DOCTOR_NGINX_IMAGE", "nginx:1.28.0-alpine3.21"))}
            os.environ.update(DOCTOR_FIXTURE_IMAGE=self.project + ":synthetic", DOCTOR_PYTHON_IMAGE=self.bases["python"], DOCTOR_NGINX_IMAGE=self.bases["nginx"])
            os.environ['DOCTOR_OBSERVER_IMAGE'] = self.project + ':observer'
            self.command(self.compose + ["build", "botapi", 'observer'])
            self.built = True
            with tempfile.TemporaryDirectory(prefix="doctor-integration-") as temporary:
                private = Path(temporary)
                inputs = private / "decisions.json"
                inputs.write_text(json.dumps(dict(schema_version=1, workflow_prepared=True, file_access="not_used",
                    delivery_action="polling", drop_pending_updates=False)), encoding="utf-8")
                inputs.chmod(0o600)
                common = ["--scenario", "official-to-self", "--migration-input", str(inputs), "--format", "json",
                          "--min-free-bytes", "1024", "--min-free-inodes", "8", "--deadline", "90"]
                def check(name, override=None, extra=(), expected=None):
                    files = [str(FIXTURES / "compose.yml")]
                    compose = list(self.compose)
                    if override:
                        path = private / (name + ".json")
                        path.write_text(json.dumps(override), encoding="utf-8")
                        files.append(str(path))
                        compose += ["-f", str(path)]
                    self.command(compose + ["up", "-d", "--wait", "--wait-timeout", "30"])
                    before = self.snapshot()
                    argv = ["-p", self.project]
                    for file in files:
                        argv += ["-f", file]
                    result, code = run_case(argv + common + list(extra))
                    after = self.snapshot()
                    if before != after:
                        raise AssertionError("synthetic sentinel changed")
                    if expected is not None and code != expected:
                        reasons = [c["reason_code"] for c in result["checks"] if c["required"] and c["status"] != "PASS"]
                        raise AssertionError(name + " unexpected result: " + ",".join(reasons))
                    cases.append({"name": name, "exit_code": code, "verdict": result["readiness"]["verdict"]})
                    return argv
                linux = sys.platform == "linux" and "docker desktop" not in json.loads(self.command(["docker", "info", "--format", "{{json .}}"])).get("OperatingSystem", "").lower()
                argv = check("safe", expected=0 if linux else 3)
                check("no-write", extra=["--no-write-probe"], expected=3)
                check("missing", {"services": {"botapi": {"environment": {"TELEGRAM_API_HASH": ""}}}}, expected=1)
                unsafe = {"services": {"gateway": {"volumes": [
                    {"type": "bind", "source": str(FIXTURES / "nginx.unsafe.conf"), "target": "/etc/nginx/conf.d/default.conf", "read_only": True},
                    {"type": "volume", "source": "state", "target": "/var/lib/telegram-bot-api", "read_only": True}]}}}
                check("unsafe", unsafe, expected=1)
                alternative = private / "alternative.conf"
                alternative.write_text('server { listen 80; location /alternate/ { root /var/lib/telegram-bot-api; } location / { proxy_pass http://botapi:8081; } }', encoding="utf-8")
                unsafe["services"]["gateway"]["volumes"][0]["source"] = str(alternative)
                check("alternative-root", unsafe, expected=1)
                wrong = private / "wrong.conf"
                wrong.write_text((FIXTURES.parent.parent / "nginx.conf").read_text().replace(":8081", ":8089"), encoding="utf-8")
                check("wrong-port", {"services": {"gateway": {"volumes": [{"type": "bind", "source": str(wrong), "target": "/etc/nginx/conf.d/default.conf", "read_only": True}]}}}, expected=1)
                check("read-only", {"services": {"botapi": {"volumes": [{"type": "volume", "source": "state", "target": "/var/lib/telegram-bot-api", "read_only": True}]}}}, expected=1)
                self.command(self.compose + ["up", "-d", "--wait", "--wait-timeout", "30"])
                self.command(self.compose + ["exec", "-T", "--user", "0:0", "botapi", "sh", "-c",
                    'chown 0:0 /tmp/telegram-bot-api; chmod 700 /tmp/telegram-bot-api; touch /tmp/telegram-bot-api/.root-capability; rm /tmp/telegram-bot-api/.root-capability'])
                _, denied = run_case(argv + common)
                if denied != 1:
                    raise AssertionError("runtime UID write denial was not a blocker")
                cases.append({"name": "uid-denied", "exit_code": denied})
                self.command(self.compose + ["exec", "-T", "--user", "0:0", "botapi", "sh", "-c", 'chown 101:101 /tmp/telegram-bot-api; chmod 755 /tmp/telegram-bot-api'])
                self.command(self.compose + ["stop", "gateway"])
                _, stopped = run_case(argv + common)
                if stopped != 1:
                    raise AssertionError("stopped service was not blocked")
                cases.append({"name": "stopped", "exit_code": stopped})
                invalid = inputs.with_name("invalid.json")
                invalid.write_text('{"bot_token":"synthetic-rejected"}', encoding="utf-8")
                invalid.chmod(0o600)
                bad_args = list(common)
                bad_args[bad_args.index(str(inputs))] = str(invalid)
                _, invalid_code = run_case(argv + bad_args)
                if invalid_code != 2:
                    raise AssertionError("invalid input was not rejected")
                raw = self.command(self.compose + ["exec", "-T", "botapi", "cat", "/audit/requests.log"])
                if any(json.loads(line) != "/" for line in raw.splitlines()):
                    raise AssertionError("a non-root synthetic HTTP request occurred")
                self.snapshot()
            return {"kind": "synthetic_integration", "bases": self.bases, "cases": cases,
                    "actual_image_smoke": "NOTRUN", "production": "NOTRUN"}
        finally:
            try:
                for signum in signals:
                    signal.signal(signum, signal.SIG_IGN)
                # No cleanup against production names or paths: the random project is the boundary.
                if os.environ.get("DOCTOR_FIXTURE_IMAGE") == self.project + ":synthetic":
                    self.stop()
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
                for signum, handler in signals.items():
                    signal.signal(signum, handler)


if __name__ == "__main__":
    try:
        print(json.dumps(Harness().run(), indent=2))
    except (Exception, KeyboardInterrupt):
        print("Synthetic doctor integration failed; inspect CI step and private fixture state.", file=sys.stderr)
        sys.exit(1)
