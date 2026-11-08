"""Injectable deterministic boundary doubles. Never imported by production doctor."""
from doctor_runtime import Budget, RunError
import copy
import json


class FakeRunner:
    def __init__(self, responses=(), clock=None):
        self.responses, self.calls = list(responses), []
        self.budget = Budget(clock=clock) if clock else Budget()

    def run(self, argv):
        self.budget.remaining()
        self.calls.append(list(argv))
        if not self.responses:
            raise RunError("unavailable")
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class FakeHttp:
    def __init__(self, responses=()):
        self.responses, self.calls = list(responses), []

    def get(self, url):
        self.calls.append(url)
        if not self.responses:
            raise RunError("http_unavailable")
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class StackRunner:
    """Complete synthetic Docker model for pure orchestration regressions."""
    def __init__(self, *, missing=False, stopped=False, unsafe=False, drift=False, changed=False, pinned=False):
        self.budget, self.calls = Budget(), []
        self.unsafe, self.changed = unsafe, changed
        self.defaults = ["TELEGRAM_WORK_DIR=/var/lib/telegram-bot-api", "TELEGRAM_TEMP_DIR=/tmp/telegram-bot-api"]
        env = {"TELEGRAM_API_ID": "12345", "TELEGRAM_API_HASH": "xy" if not missing else "", "TELEGRAM_LOCAL": "true"}
        self.model = {"name": "doctor-unit", "services": {
            "botapi": {"image": "synthetic@sha256:" + "9" * 64 if pinned else "synthetic", "environment": env,
                       "volumes": [{"type": "volume", "source": "state", "target": "/var/lib/telegram-bot-api"}]},
            "gateway": {"image": "synthetic-nginx", "ports": [{"target": 80, "published": "18080", "host_ip": "127.0.0.1"}]}}}
        self.containers = []
        self.images = {}
        for service, letter, digit in (("botapi", "a", "1"), ("gateway", "b", "2")):
            image = "sha256:" + digit * 64
            config = {"Env": self.defaults + [k + "=" + v for k, v in env.items()] if service == "botapi" else [],
                      "Entrypoint": ["/docker-entrypoint.sh"], "Cmd": [], "Image": self.model["services"][service]["image"],
                      "Labels": {"com.docker.compose.project": "doctor-unit", "com.docker.compose.service": service,
                                 "com.docker.compose.oneoff": "False"}}
            mounts = [{"Type": "volume", "Name": "doctor-unit_state", "Destination": "/var/lib/telegram-bot-api", "Source": "/volumes/doctor-state", "RW": service == "botapi"}]
            container = {"Id": letter * 64, "Image": image, "Config": config,
                         "State": {"Running": not (stopped and service == "gateway"), "Pid": 101, "StartedAt": "synthetic-start"},
                         "Mounts": mounts if service == "botapi" or unsafe else [],
                         "NetworkSettings": {"Networks": {"doctor-unit_default": {"Aliases": [service], "IPAddress": "172.19.0.2" if service == "botapi" else "172.19.0.3"}},
                                             "Ports": {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18080"}]} if service == "gateway" else {}}}
            self.containers.append(container)
            self.images[image] = {"Id": image, "RepoDigests": [], "Os": "linux", "Architecture": "amd64",
                                  "Config": {"Env": self.defaults if service == "botapi" else [], "Labels": {}}}
        if drift:
            self.containers[0]["Config"]["Env"][-1] = "TELEGRAM_LOCAL=false"

    def run(self, argv):
        self.calls.append(list(argv))
        if argv[:2] == ["docker", "compose"]:
            return 0, json.dumps(self.model).encode()
        if argv[:2] == ["docker", "info"]:
            return 0, b'{"OSType":"linux","OperatingSystem":"Synthetic Linux","SecurityOptions":[]}'
        if argv[:2] == ["docker", "context"]:
            return 0, b'"unix:///var/run/docker.sock"'
        if argv[:2] == ["docker", "ps"]:
            return 0, b"aaaaaaaaaaaa\nbbbbbbbbbbbb\n"
        if argv[:3] == ["docker", "image", "inspect"]:
            return 0, json.dumps([self.images[argv[-1]]]).encode()
        if argv[:2] == ["docker", "inspect"]:
            selected = copy.deepcopy(self.containers if len(argv) > 3 else [c for c in self.containers if c["Id"] == argv[2]])
            if self.changed and len(argv) == 3:
                selected[0]["State"]["Pid"] = 999
            return 0, json.dumps(selected).encode()
        if "exec" in argv:
            if "--version" in argv:
                return 0, b"Bot API 0.0.0\n"
            if any("nginx -v" in value for value in argv):
                return 0, b"nginx version: nginx/1.28.0\n"
            if any("nginx -T" in value for value in argv):
                alias = "location /file/ { alias /var/lib/telegram-bot-api/; }" if self.unsafe else ""
                return 0, ("server { listen 80; " + alias + " location / { proxy_pass http://botapi:8081; } }").encode()
            if any("DOCTOR_ARGV" in value for value in argv):
                return 0, b"/usr/local/bin/telegram-bot-api\nUid:\t101\t101\t101\t101\nGid:\t101\t101\t101\t101\nGroups:\t101\n\nDOCTOR_ARGV\ntelegram-bot-api\0--dir=/var/lib/telegram-bot-api\0--temp-dir=/tmp/telegram-bot-api\0--http-port=8081\0--local\0"
            if any("stat -f" in value for value in argv):
                return 0, b"1:2\nsynthetic-fs 4096 9999999 999999\n101\n101\n101\nDOCTOR_MOUNTINFO\n1 0 0:1 / / rw - ext4 /synthetic rw\n"
            if "timeout" in argv:
                return 0, b"OK\n"
        raise AssertionError("unexpected synthetic command")
