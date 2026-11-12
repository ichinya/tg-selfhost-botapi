"""Bounded subprocess runner; never expose raw errors to the report."""
import queue
import subprocess
import threading
import time
import json
import sys
import base64
import os
import re
import ipaddress
import stat
import hashlib
from urllib.parse import urlsplit


STORAGE_METADATA = r'''set -eu
test -d "$1" || exit 20
test "$(readlink -f "$1")" = "$1" || exit 21
stat -c '%d:%i' "$1"
stat -f -c '%i %S %a %d' "$1"
id -u; id -g; id -G
printf 'DOCTOR_MOUNTINFO\n'
cat /proc/self/mountinfo
'''

WRITE_PROBE = r'''set -eu
dir=$1
test -d "$dir" || exit 20
test "$(readlink -f "$dir")" = "$dir" || exit 21
test "$(id -u)" = "$2" && test "$(id -g)" = "$3" || exit 22
actual_groups=$(id -G | tr ' ' '\n' | sort -nu | tr '\n' ' ')
test "$actual_groups" = "$4" || exit 22
before=$(stat -c '%d:%i' "$dir")
cd -P "$dir" || exit 20
test "$before" = "$(stat -c '%d:%i' .)" || exit 21
case "$5" in ''|*[!a-f0-9]*) exit 22;; esac
probe=".doctor-$5"
cleanup() {
    if [ -n "$probe" ] && { [ -e "$probe" ] || [ -L "$probe" ]; }; then
        own=$(stat -L -c '%d:%i' /proc/$$/fd/3) || { printf 'CLEANUP_FAILED\n'; exit 24; }
        current=$(stat -c '%d:%i' "$probe") || { printf 'CLEANUP_FAILED\n'; exit 24; }
        if [ "$own" != "$current" ] || ! rm -- "$probe" || [ -e "$probe" ] || [ -L "$probe" ]; then
            printf 'CLEANUP_FAILED\n'; exit 24
        fi
    fi
    probe=''
}
trap cleanup EXIT
trap 'exit 25' HUP INT TERM
# noclobber opens exclusively. Keep the descriptor open through verification
# and cleanup; never reopen a pathname which another writer could replace.
set -C
exec 3>"$probe" || exit 23
printf 'doctor\n' >&3 || exit 23
test "$(stat -L -c '%s' /proc/$$/fd/3)" -eq 7 || exit 23
test "$(readlink -f "$dir")" = "$dir" && test "$before" = "$(stat -c '%d:%i' "$dir")" || exit 21
cleanup
printf 'OK\n'
'''


TRANSFER_METADATA = r'''set -eu
export LC_ALL=C
work=$1
dir=$work
if [ "$2" != . ]; then dir=$work/$2; fi
test -d "$dir" && test ! -L "$dir" || exit 20
test "$(readlink -f "$work")" = "$work" || exit 21
test "$(readlink -f "$dir")" = "$dir" || exit 21
find "$dir" -xdev -exec stat -c '%F|%s|%i|%Y|%Z|%d' {} +
'''

TARGET_DESTINATION = r'''set -eu
work=$1
test -d "$work" && test "$(readlink -f "$work")" = "$work" || exit 21
if [ "$2" = . ]; then
    entries=$(find "$work" -mindepth 1 -maxdepth 1 -exec printf x \; -quit) || exit 21
    test -z "$entries" || { printf 'OCCUPIED\n'; exit 0; }
else
    test ! -e "$work/$2" && test ! -L "$work/$2" || { printf 'OCCUPIED\n'; exit 0; }
fi
printf 'EMPTY\n'
'''


def transfer_metadata(raw):
    entries = raw.decode("ascii").splitlines()
    if not entries or len(entries) > 50000:
        raise ValueError("transfer metadata limit")
    total, seen = 0, set()
    for entry in entries:
        kind, size, inode, mtime, ctime, device = entry.split("|")
        if kind not in {"regular file", "regular empty file", "directory"}:
            raise ValueError("unsupported state entry")
        numbers = [int(v) for v in (size, inode, mtime, ctime)]
        if min(numbers[:2]) < 0 or numbers[0] > 2**63 - 1:
            raise ValueError("invalid metadata")
        key = (int(device), numbers[1])
        if key not in seen:
            if key[0] < 0:
                raise ValueError("invalid metadata device")
            total += numbers[0]
            seen.add(key)
        if total > 2**63 - 1:
            raise ValueError("transfer size limit")
    return total, len(entries)


def mount_accounting(lines, path):
    """Container mount metadata, without exposing paths or assuming quota headroom."""
    mounts = []
    for line in lines:
        fields = line.split()
        separator = fields.index("-")
        point = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[4])
        options = set(fields[5].split(",")) | set(fields[separator + 3].split(","))
        mounts.append((point, options))
    selected = [m for m in mounts if path == m[0] or path.startswith(m[0].rstrip("/") + "/")]
    if not selected:
        raise ValueError("filesystem accounting unavailable")
    _, options = max(selected, key=lambda m: len(m[0]))
    return [m[0] for m in mounts], any("quota" in option and option != "noquota" for option in options)


class RunError(Exception):
    pass


class CapabilityError(Exception):
    """The selected Compose invocation/configuration cannot provide JSON."""


class Budget:
    def __init__(self, timeout=5, deadline=60, clock=time.monotonic):
        self.timeout, self.clock, self.end = timeout, clock, clock() + deadline

    def remaining(self):
        value = min(self.timeout, self.end - self.clock())
        if value <= 0:
            raise RunError("deadline")
        return value


class Runner:
    def __init__(self, timeout=5, deadline=60, max_output=8 * 1024 * 1024, clock=time.monotonic, budget=None):
        self.budget = budget or Budget(timeout, deadline, clock)
        self.max_output, self.clock = max_output, self.budget.clock

    def run(self, argv):
        remaining = self.budget.remaining()
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, shell=False)
        except OSError:
            raise RunError("unavailable") from None
        events, stop = queue.Queue(maxsize=16), threading.Event()
        def emit(item):
            while not stop.is_set():
                try:
                    events.put(item, timeout=0.1)
                    return
                except queue.Full:
                    pass
        def read(stream, name):
            try:
                while not stop.is_set():
                    data = stream.read1(65536)
                    if not data:
                        break
                    emit((name, data))
            finally:
                stream.close()
                emit((name, None))
        readers = [threading.Thread(target=read, args=(stream, name), daemon=True)
                   for name, stream in (("out", proc.stdout), ("err", proc.stderr))]
        for reader in readers:
            reader.start()
        output, done, size = bytearray(), 0, 0
        end = self.clock() + remaining
        try:
            while done < 2:
                wait = end - self.clock()
                if wait <= 0:
                    raise RunError("timeout")
                try:
                    name, data = events.get(timeout=wait)
                except queue.Empty:
                    raise RunError("timeout") from None
                if data is None:
                    done += 1
                    continue
                size += len(data)
                if size > self.max_output:
                    raise RunError("overflow")
                if name == "out":
                    output.extend(data)
            try:
                code = proc.wait(timeout=max(0.001, end - self.clock()))
            except subprocess.TimeoutExpired:
                raise RunError("timeout") from None
            return code, bytes(output)
        finally:
            stop.set()
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            for reader in readers:
                reader.join(timeout=0.5)


def endpoint(value):
    """Validate before any networking; deployment prefixes are mapped by the collector."""
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) <= 32 for c in value):
        raise ValueError("invalid endpoint")
    u = urlsplit(value)
    if (u.scheme not in {"http", "https"} or not u.hostname or u.username is not None
            or u.password is not None or "?" in value or "#" in value or "%" in value or "\\" in value
            or any(p in {".", ".."} or p.lower().startswith("bot") for p in u.path.split("/"))
            or u.hostname.lower().rstrip(".") == "api.telegram.org"):
        raise ValueError("invalid endpoint")
    if u.port is not None and not 1 <= u.port <= 65535:
        raise ValueError("invalid endpoint")
    return u


class Http:
    """A killable worker bounds DNS, TLS and the entire body, with the shared budget."""
    def __init__(self, runner):
        self.runner = runner

    def get(self, url):
        if endpoint(url).path not in {"", "/"}:
            raise ValueError("only root HTTP probes are supported")
        code, output = self.runner.run([sys.executable, __file__, "--http-worker", url,
                                       str(self.runner.budget.remaining())])
        if code:
            raise RunError("http_unavailable")
        try:
            item = json.loads(output)
            return item["status"], item["content_type"], base64.b64decode(item["body"], validate=True)
        except (ValueError, KeyError, TypeError):
            raise RunError("http_invalid") from None


def http_worker(url, timeout):
    import http.client
    import ssl
    u = endpoint(url)
    if u.path not in {"", "/"}:
        raise ValueError("only root HTTP probes are supported")
    connection = (http.client.HTTPSConnection(u.hostname, u.port, timeout=timeout, context=ssl.create_default_context())
                  if u.scheme == "https" else http.client.HTTPConnection(u.hostname, u.port, timeout=timeout))
    end = time.monotonic() + timeout
    try:
        connection.request("GET", u.path or "/", headers={"Connection": "close"})
        response = connection.getresponse()
        body = bytearray()
        while len(body) <= 16384:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise RunError("timeout")
            if connection.sock:
                connection.sock.settimeout(remaining)
            chunk = response.read1(min(4096, 16385 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
        if len(body) > 16384:
            raise RunError("overflow")
        return {"status": response.status, "content_type": response.getheader("Content-Type", "")[:128],
                "body": base64.b64encode(body).decode("ascii")}
    finally:
        connection.close()


def compose_argv(args, source=False):
    prefix = "source_" if source else ""
    argv = ["docker", "compose"]
    for name in ("file", "env_file", "profile", "project_directory", "project_name"):
        value = getattr(args, prefix + name, None)
        for item in (value if isinstance(value, list) else [value] if value is not None else []):
            argv += ["--" + name.replace("_", "-"), item]
    return argv


def load_migration_input(path):
    from doctor_checks import validate_migration_input
    if path is None:
        return {}, True
    from pathlib import Path
    # Inputs never belong to a checkout or a symlinked directory tree.
    absolute = Path(os.path.abspath(path))
    for parent in (absolute, *absolute.parents):
        if parent.is_symlink() or (parent.is_dir() and (parent / ".git").exists()):
            raise ValueError("input location")
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or before.st_size > 32768:
        raise ValueError("invalid private input")
    secure = True if os.name == "posix" else None
    if secure and (before.st_mode & 0o077 or before.st_uid != os.getuid()):
        return {}, False
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    with os.fdopen(fd, "rb") as stream:
        current = os.fstat(stream.fileno())
        if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("input changed")
        raw = stream.read(32769)
        if len(raw) > 32768:
            raise ValueError("input limit")
    return parse_migration_input(raw), secure


def parse_migration_input(raw):
    from doctor_checks import validate_migration_input
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError("duplicate input field")
            result[k] = v
        return result
    def invalid_constant(value):
        raise ValueError("non-finite input")
    return validate_migration_input(json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant))


class Installation:
    def __init__(self, args, runner, http, checks, images, source=False):
        self.args, self.runner, self.http, self.checks, self.images = args, runner, http, checks, images
        self.source = source
        self.role = "source" if source or args.scenario == "self-to-official" else "target"
        self.compose = compose_argv(args, source)
        self.config, self.containers, self.image_data = {}, {}, {}
        self.info, self.process = {}, None
        self.storage_data = {}
        self.gateway_route_verified = False
        self.nginx_snapshot = None

    def add(self, name, status, reason, message, **kw):
        from doctor_checks import check
        self.checks.append(check(self.role + "." + name, status, reason, message, **kw))

    def command(self, argv):
        code, data = self.runner.run(argv)
        if code:
            raise RunError("command_failed")
        return data

    def json(self, argv):
        try:
            return json.loads(self.command(argv))
        except (ValueError, UnicodeError):
            raise RunError("invalid_runtime_json") from None

    def configuration(self):
        from doctor_checks import environment, settings_checks, container_state
        code, raw = self.runner.run(self.compose + ["config", "--format", "json"])
        if code:
            raise CapabilityError("compose_config_unavailable")
        try:
            self.config = json.loads(raw)
        except (ValueError, UnicodeError):
            raise CapabilityError("compose_json_unsupported") from None
        if not isinstance(self.config, dict):
            raise CapabilityError("compose_json_unsupported")
        services = self.config.get("services", {})
        if not isinstance(services, dict) or len(services) > 32:
            raise RunError("unsupported_topology")
        for service in ("botapi", "gateway"):
            self.add(service + ".configured", "pass" if service in services else "fail", "configured" if service in services else "missing_service", "Required Compose service presence.")
        try:
            self.info = self.json(["docker", "info", "--format", "{{json .}}"])
            if self.info.get("OSType") != "linux":
                self.add("engine", "unknown", "unsupported_engine", "Linux containers are required.")
                return
            self.add("engine", "pass", "available", "Docker Linux engine is reachable.")
        except RunError:
            env = environment(services.get("botapi", {}).get("environment"))
            self.checks.extend(settings_checks(env, self.role, bool(services.get("botapi", {}).get("command")), defaults_known=False))
            self.add("engine", "unknown", "daemon_unavailable", "Runtime evidence is unavailable.")
            return
        project = self.config.get("name")
        if not isinstance(project, str) or not project or len(project) > 128:
            raise RunError("project_unknown")
        ids = self.command(["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + project]).decode("ascii").split()
        if len(ids) > 32 or any(not all(c in "0123456789abcdef" for c in i) for i in ids):
            raise RunError("container_limit")
        all_containers = self.json(["docker", "inspect", *ids]) if ids else []
        for service in services:
            candidates = [c for c in all_containers if c.get("Config", {}).get("Labels", {}).get("com.docker.compose.service") == service
                          and c.get("Config", {}).get("Labels", {}).get("com.docker.compose.project") == project
                          and c.get("Config", {}).get("Labels", {}).get("com.docker.compose.oneoff", "false").lower() == "false"]
            required = service in {"botapi", "gateway"}
            if len(candidates) != 1:
                self.add(service + ".runtime", "fail" if not candidates else "unknown", "missing_service" if not candidates else "ambiguous_replicas", "Exactly one selected service container is required.", required=required)
                continue
            container = candidates[0]
            self.containers[service] = container
            status, reason = container_state(container)
            self.add(service + ".running", status, reason, "Selected service process state.", required=required)
            self.image_data[service] = self.json(["docker", "image", "inspect", container["Image"]])[0]
            desired = services[service]
            actual = container.get("Config", {})
            actual_env = environment(actual.get("Env"))
            desired_env = environment(self.image_data[service].get("Config", {}).get("Env"))
            desired_env.update(environment(desired.get("environment")))
            drift = actual_env != desired_env
            if desired.get("image") and actual.get("Image") != desired["image"]:
                drift = True
            for key, runtime_key in (("command", "Cmd"), ("entrypoint", "Entrypoint")):
                expected = desired.get(key) if desired.get(key) is not None else self.image_data[service].get("Config", {}).get(runtime_key)
                if expected and expected != actual.get(runtime_key):
                    drift = True
            for mount in desired.get("volumes", []):
                matches = [m for m in container.get("Mounts", []) if m.get("Destination") == mount.get("target")]
                if not matches or bool(mount.get("read_only", False)) == bool(matches[0].get("RW")):
                    drift = True
                elif mount.get("type") == "bind" and matches[0].get("Source") != mount.get("source"):
                    # Docker Desktop may translate bind paths; it cannot establish exact parity.
                    self.add(service + ".bind_mapping", "unknown", "bind_mapping_unverified", "Bind path mapping is not identical to the Compose model.", required=required)
                elif mount.get("type") == "volume":
                    definition = self.config.get("volumes", {}).get(mount.get("source"), {})
                    volume_name = definition.get("name") or project + "_" + str(mount.get("source"))
                    if matches[0].get("Name") != volume_name:
                        drift = True
            expected_mounts = {m.get("target") for m in desired.get("volumes", [])}
            expected_mounts.update(self.image_data[service].get("Config", {}).get("Volumes") or {})
            if any(m.get("Destination") not in expected_mounts for m in container.get("Mounts", [])):
                drift = True
            if desired.get("volumes_from"):
                self.add(service + ".mount_sources", "unknown", "volumes_from_unverified", "Inherited mount sources require separate topology evidence.")
            for port in desired.get("ports", []):
                target = str(port.get("target")) + "/" + port.get("protocol", "tcp")
                bindings = container.get("NetworkSettings", {}).get("Ports", {}).get(target) or []
                published = str(port.get("published", "0"))
                if not bindings or (published not in {"0", ""} and not any(b.get("HostPort") == published for b in bindings)):
                    drift = True
                if published not in {"0", ""} and any(b.get("HostPort") != published for b in bindings):
                    drift = True
                if port.get("host_ip") and not any(b.get("HostIp") == port["host_ip"] for b in bindings):
                    drift = True
                if port.get("host_ip") and any(b.get("HostIp") != port["host_ip"] for b in bindings):
                    drift = True
            expected_ports = {str(p.get("target")) + "/" + p.get("protocol", "tcp") for p in desired.get("ports", [])}
            if any(values and key not in expected_ports for key, values in container.get("NetworkSettings", {}).get("Ports", {}).items()):
                drift = True
            if container.get("HostConfig", {}).get("NetworkMode") == "host":
                self.add(service + ".host_network", "unknown", "host_network_unverified", "Host networking requires separate listener and exposure evidence.")
            host_config = container.get("HostConfig", {})
            if host_config.get("Privileged") or any(c in {"SYS_ADMIN", "CAP_SYS_ADMIN", "ALL"} for c in host_config.get("CapAdd") or []):
                self.add(service + ".mount_namespace", "unknown", "mutable_mount_namespace", "A privileged component can change mounts outside the observed Docker topology.")
            self.add(service + ".drift", "fail" if drift else "pass", "runtime_drift" if drift else "consistent", "Effective Compose settings compared with selected container.", required=required)
            if service == "botapi":
                explicit = bool(actual.get("Cmd"))
                self.checks.extend(settings_checks(actual_env, self.role, explicit))
                if not explicit:
                    for name in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH"):
                        if actual_env.get(name + "_FILE") and not actual_env.get(name):
                            duration = str(max(0.1, min(2.0, self.runner.budget.remaining() - 1)))
                            code, _ = self.runner.run(["docker", "exec", container["Id"], "timeout", "-s", "TERM", "-k", "0.5", duration, "sh", "-c",
                                'test -f "$1" && test -r "$1" && test -s "$1"', "doctor", actual_env[name + "_FILE"]])
                            for c in self.checks:
                                if c["id"] == self.role + "." + name.lower():
                                    c.update(status="pass" if code == 0 else "fail" if code == 1 else "unknown", reason_code="secret_file_present" if code == 0 else "secret_file_unreadable" if code == 1 else "secret_file_unverified")
                supported = actual.get("Entrypoint") == ["/docker-entrypoint.sh"]
                self.add("entrypoint", "pass" if supported else "unknown", "supported" if supported else "custom_entrypoint", "Entrypoint contract coverage.")
        if "botapi" in self.containers and "gateway" in self.containers:
            nets = [set(self.containers[s].get("NetworkSettings", {}).get("Networks", {})) for s in ("botapi", "gateway")]
            self.add("network", "pass" if nets[0] & nets[1] else "fail", "connected" if nets[0] & nets[1] else "network_mismatch", "API and gateway need a shared network.")
            api_networks = self.containers["botapi"].get("NetworkSettings", {}).get("Networks", {})
            shared = [api_networks[n] for n in nets[0] & nets[1]]
            alias = any("botapi" in (n.get("Aliases") or []) + (n.get("DNSNames") or []) for n in shared)
            known = bool(shared) and all("Aliases" in n or "DNSNames" in n for n in shared)
            collision = any("botapi" in (n.get("Aliases") or []) + (n.get("DNSNames") or [])
                            for service, c in self.containers.items() if service != "botapi"
                            for name, n in c.get("NetworkSettings", {}).get("Networks", {}).items() if name in nets[0] & nets[1])
            self.add("upstream_alias", "fail" if collision else "pass" if alias else "fail" if known else "unknown", "alias_collision" if collision else "alias_matched" if alias else "alias_missing" if known else "alias_unverified", "The upstream service alias must belong to the selected API on the shared network.")
            external = any(n.get("external") for n in self.config.get("networks", {}).values())
            self.add("network_topology", "unknown" if external else "pass", "shared_network_unverified" if external else "compose_network", "External shared networks need independent route identity evidence.")
            for service in ("botapi", "gateway"):
                desired_nets = services[service].get("networks") or {"default": None}
                expected = {self.config.get("networks", {}).get(n, {}).get("name") or project + "_" + n for n in desired_nets}
                actual_nets = set(self.containers[service].get("NetworkSettings", {}).get("Networks", {}))
                if expected != actual_nets:
                    self.add(service + ".network_drift", "fail", "runtime_drift", "Runtime network membership differs from the selected Compose model.")
        if any(s.get("container_name") for s in services.values()):
            self.add("fixed_names", "unknown", "fixed_container_name", "Fixed names may conflict with another stack.", required=False, severity="warning")

    def unchanged(self):
        from doctor_checks import runtime_identity
        same_model = True
        if self.containers:
            same_model = self.json(self.compose + ["config", "--format", "json"]) == self.config
            self.add("compose_snapshot", "pass" if same_model else "unknown", "consistent" if same_model else "runtime_changed", "Effective Compose model was checked again at the end.")
        for service, container in self.containers.items():
            current = self.json(["docker", "inspect", container["Id"]])[0]
            same = same_model and runtime_identity(current) == runtime_identity(container)
            if service == "gateway" and self.nginx_snapshot is not None:
                raw = self.exec("gateway", "sh", "-c", "nginx -T 2>/dev/null")
                same = same and hashlib.sha256(raw).digest() == self.nginx_snapshot
            if not same:
                for finding in self.checks:
                    if finding["id"].startswith(self.role + ".") and finding["status"] == "pass":
                        finding.update(status="unknown", reason_code="runtime_changed", message="Runtime changed after this evidence was collected.")
            self.add(service + ".snapshot", "pass" if same else "unknown", "consistent" if same else "runtime_changed", "Container identity was checked again at the end.", required=service in {"botapi", "gateway"})

    def exec(self, service, program, *args, user=None):
        container = self.containers[service]
        argv = ["docker", "exec"]
        if user is not None:
            argv += ["--user", user]
        # A host CLI timeout cannot stop a container exec by itself.
        command = [program, *args]
        if program != "timeout":
            duration = str(max(0.1, min(2.0, self.runner.budget.remaining() - 1)))
            command = ["timeout", "-s", "TERM", "-k", "0.5", duration, *command]
        return self.command(argv + [container["Id"], *command])

    def runtime(self):
        from doctor_checks import environment, process_flags, valid_port
        for service, container in self.containers.items():
            image = self.image_data.get(service, {})
            actual_id = container.get("Image", "")
            good_id = bool(re.fullmatch(r"sha256:[a-f0-9]{64}", actual_id)) and image.get("Id") == actual_id
            digests = [d for d in image.get("RepoDigests", []) or [] if isinstance(d, str) and re.fullmatch(r"[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}", d)]
            desired_ref = self.config["services"][service].get("image", "")
            pinned = desired_ref.split("@", 1)[1] if "@" in desired_ref else None
            if pinned:
                match = any(d.endswith("@" + pinned) for d in digests)
                self.add(service + ".pinned_digest", "pass" if match else "fail" if digests else "unknown", "digest_matched" if match else "digest_mismatch" if digests else "registry_digest_absent", "Pinned registry digest compared with actual image metadata.")
            self.add(service + ".image", "pass" if good_id else "unknown", "actual_image" if good_id else "image_identity_unverified", "Actual container image config identity.", required=service in {"botapi", "gateway"})
            local_build = bool(self.config["services"][service].get("build"))
            digest_reason = "observed" if digests else "local_build" if local_build else "registry_digest_unavailable"
            self.add(service + ".registry_digest", "pass" if digests else "unknown", digest_reason, "Registry identity may be absent for local builds; image ID is separate.", required=False)
            version = None
            if container.get("State", {}).get("Running"):
                try:
                    raw = (self.exec(service, "telegram-bot-api", "--version") if service == "botapi" else
                           self.exec(service, "sh", "-c", "nginx -v 2>&1") if service == "gateway" else b"")
                    pattern = rb"(?:Bot API|telegram-bot-api|nginx(?: version)?: nginx/)[^\r\n]{0,24}?([0-9]+\.[0-9]+(?:\.[0-9]+)?)"
                    found = re.search(pattern, raw, re.I)
                    if found:
                        version = found.group(1).decode("ascii")
                except RunError:
                    pass
            self.add(service + ".version", "pass" if version else "unknown", "observed" if version else "version_unavailable", "Binary version collected from the selected running service.", required=service in {"botapi", "gateway"})
            # Never publish repository names, arbitrary image refs or labels from private config.
            labels = image.get("Config", {}).get("Labels", {}) or {}
            safe_labels = {k: v for k, v in labels.items() if k in {"io.tg-selfhost.bot-api-revision", "io.tg-selfhost.build-key"}
                           and isinstance(v, str) and re.fullmatch(r"[a-f0-9]{7,64}|local", v)}
            self.images.append({"role": self.role + "." + service if service in {"botapi", "gateway", "downloads"} else self.role + ".optional",
                                "container_id": container.get("Id", "") if re.fullmatch(r"[a-f0-9]{64}", container.get("Id", "")) else None,
                                "creation_reference": "[selected image reference]", "image_id": actual_id if good_id else None,
                                "registry_digests": ["[selected registry image]@" + d.rsplit("@", 1)[1] for d in digests[:64]], "registry_digest_reason": digest_reason,
                                "platform": image.get("Os") + "/" + image.get("Architecture") if image.get("Os") in {"linux", "windows"} and image.get("Architecture") in {"amd64", "arm64", "arm", "386"} else "unknown",
                                "version": version, "labels": safe_labels})
        container = self.containers.get("botapi")
        if not container or not container.get("State", {}).get("Running"):
            return
        try:
            # Raw argv and status are kept in memory only. PID 1 must be the server,
            # or the explicitly identified synthetic integration interpreter.
            raw = self.exec("botapi", "sh", "-c", 'readlink /proc/1/exe; cat /proc/1/status; printf "\\nDOCTOR_ARGV\\n"; cat /proc/1/cmdline')
            head, argv_raw = raw.split(b"\nDOCTOR_ARGV\n", 1)
            lines = head.decode("utf-8").splitlines()
            executable = lines[0]
            argv = [a.decode("utf-8") for a in argv_raw.split(b"\0") if a]
            synthetic = self.image_data["botapi"].get("Config", {}).get("Labels", {}).get("io.tg-selfhost.doctor-fixture") == "synthetic"
            if executable.rsplit("/", 1)[-1] == "telegram-bot-api":
                flags = process_flags(argv[1:])
            elif synthetic and len(argv) >= 2 and argv[1] == "/usr/local/bin/telegram-bot-api":
                flags = process_flags(argv[2:])
                self.add("synthetic_runtime", "pass", "synthetic_fixture", "Synthetic process: this run does not verify the Telegram binary.", required=False, severity="info")
            else:
                raise ValueError
            values = dict(line.split(":", 1) for line in lines[1:] if ":" in line)
            uid, gid = values["Uid"].split(), values["Gid"].split()
            groups = sorted(int(g) for g in values["Groups"].split())
            if len(uid) != 4 or len(gid) != 4 or len(set(uid)) != 1 or len(set(gid)) != 1:
                raise ValueError
            self.process = {"uid": int(uid[1]), "gid": int(gid[1]), "groups": groups, "flags": flags,
                            "work": flags.get("dir"), "temp": flags.get("temp-dir"),
                            "files": flags.get("files-dir") or flags.get("dir"),
                            "port": flags.get("http-port", "8081")}
            self.add("process", "pass", "observed_process", "Server argv and effective UID/GID/groups were observed in its namespace.")
            explicit = bool(container.get("Config", {}).get("Cmd"))
            if explicit:
                self.checks[:] = [c for c in self.checks if c["id"] != self.role + ".settings"]
                credentials = bool(flags.get("api-id")) and bool(flags.get("api-hash"))
                # Credentials can also be inherited by the official executable from environment.
                env = environment(container.get("Config", {}).get("Env"))
                credentials = credentials or (bool(env.get("TELEGRAM_API_ID")) and bool(env.get("TELEGRAM_API_HASH")))
                self.add("explicit_credentials", "pass" if credentials else "unknown", "configured" if credentials else "credentials_unverified", "Explicit command credential presence; values remain private.")
            self.add("process_port", "pass" if valid_port(self.process["port"]) else "fail", "configured" if valid_port(self.process["port"]) else "invalid_port", "Observed process listener port.")
            if flags.get("http-stat-port") == self.process["port"]:
                self.add("process_ports", "fail", "port_conflict", "Observed API and statistics ports conflict.")
        except (RunError, ValueError, KeyError, UnicodeError):
            self.add("process", "unknown", "process_unverified", "A custom process or unavailable proc evidence prevents verification.")

    def local_bridge(self):
        if sys.platform != "linux" or not self.info or self.info.get("OSType") != "linux":
            return False
        if os.environ.get("DOCKER_CONTEXT") and os.environ.get("DOCKER_HOST"):
            return False
        if "docker desktop" in self.info.get("OperatingSystem", "").lower() or any("rootless" in s for s in self.info.get("SecurityOptions", [])):
            return False
        try:
            host = os.environ.get("DOCKER_HOST") or self.json(["docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"])
            return isinstance(host, str) and host.startswith("unix://")
        except RunError:
            return False

    def published_routes_supported(self):
        if not self.info or self.info.get("OSType") != "linux":
            return False
        try:
            if os.environ.get("DOCKER_CONTEXT") and os.environ.get("DOCKER_HOST"):
                return False
            host = os.environ.get("DOCKER_HOST") or self.json(["docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"])
            return isinstance(host, str) and host.startswith(("unix://", "npipe://"))
        except RunError:
            return False

    def probe(self, name, url):
        from doctor_checks import root_response
        try:
            response = self.http.get(url)
            good = root_response(*response)
            self.add(name, "pass" if good else "fail", "root_contract" if good else "unexpected_response", "Token-free root response contract.")
        except (RunError, OSError):
            supported = name != "direct_http" or self.local_bridge()
            self.add(name, "fail" if supported else "unknown", "endpoint_unavailable", "The token-free route could not be reached from this observation point.")

    def gateway_endpoint(self):
        container = self.containers.get("gateway", {})
        bindings = []
        for port, values in container.get("NetworkSettings", {}).get("Ports", {}).items():
            if port.endswith("/tcp"):
                for value in values or []:
                    try:
                        address = ipaddress.ip_address(value["HostIp"])
                        host = "::1" if address.version == 6 and address.is_unspecified else "127.0.0.1" if address.is_unspecified else str(address)
                        if address.version == 6:
                            host = "[" + host + "]"
                        bindings.append(("http://" + host + ":" + value["HostPort"] + "/", port))
                    except (KeyError, ValueError):
                        continue
        explicit = self.args.source_gateway_url if self.source else self.args.gateway_url
        if explicit:
            u = endpoint(explicit)
            for url, port in bindings:
                b = endpoint(url)
                if u.scheme == b.scheme and u.hostname == b.hostname and (u.port or 80) == (b.port or 80) and u.path in {"", "/"}:
                    return explicit.rstrip("/") + "/", port
            return None, None
        if len(bindings) == 1:
            return bindings[0]
        return None, None

    def probes(self):
        from doctor_checks import valid_port
        safe_api_port = self.process and valid_port(self.process["port"]) and self.process.get("flags", {}).get("http-stat-port") != self.process["port"]
        if safe_api_port and self.local_bridge():
            addresses = [n.get("IPAddress") for n in self.containers["botapi"].get("NetworkSettings", {}).get("Networks", {}).values() if n.get("IPAddress")]
            if len(addresses) == 1:
                ipaddress.ip_address(addresses[0])
                self.probe("direct_http", "http://" + addresses[0] + ":" + str(self.process["port"]) + "/")
            else:
                self.add("direct_http", "unknown", "ambiguous_runtime_address", "Direct runtime route is ambiguous.")
        else:
            self.add("direct_http", "unknown", "unsupported_observation_point", "Direct bridge observation requires a local Linux engine and an observed process.")
        url, port = self.gateway_endpoint()
        if url and self.gateway_route_verified and self.published_routes_supported():
            self.probe("gateway_http", url)
        else:
            self.add("gateway_http", "unknown", "endpoint_mapping_unverified", "A local engine and an unambiguous published gateway binding are required; remote engines and external prefixes need independent mapping evidence.")

    def storage(self):
        from doctor_checks import mount_for, capacity, media_conflicts, environment
        if not self.process:
            self.add("storage", "unknown", "identity_unverified", "Storage checks need the observed server identity.")
            return
        process = self.process
        media = process.get('files') or process.get('work')
        mounts = self.containers['botapi'].get('Mounts', [])
        env = environment(self.containers['botapi'].get('Config', {}).get('Env'))
        split = bool(media and media != process.get('work'))
        if split:
            private = [p for p in (process.get('work'), process.get('temp'),
                       process.get('flags', {}).get('log') or env.get('TELEGRAM_LOG_FILE'),
                       env.get('TELEGRAM_API_ID_FILE'), env.get('TELEGRAM_API_HASH_FILE')) if p]
            conflicts = media_conflicts(media, private, mounts)
            self.add('media.isolation', 'fail' if conflicts else 'unknown' if conflicts is None else 'pass',
                     'media_private_overlap' if conflicts else 'media_paths_unverified' if conflicts is None else 'media_separated',
                     'Observed media and private paths/backings compared; this does not verify consumer mapping.')
        elif env.get('TELEGRAM_FILES_DIR'):
            self.add('media.configuration', 'unknown', 'files_dir_not_observed',
                     'Declared split storage is not present in the observed process; legacy files remain private.')
        user = str(process["uid"]) + ":" + str(process["gid"])
        expected_groups = sorted(set(process["groups"]) | {process["gid"]})
        filesystems = set()
        for role in (("work", "temp", "media") if split else ("work", "temp")):
            path = media if role == 'media' else process.get(role)
            if not isinstance(path, str) or not path.startswith("/") or path != __import__("posixpath").normpath(path):
                self.add(role + ".directory", "unknown", "directory_unverified", "An observed canonical absolute directory is required.")
                continue
            mount = mount_for(path, self.containers["botapi"].get("Mounts", []))
            if role in {"work", "media"}:
                persistent = mount and mount.get("Type") in {"bind", "volume"}
                self.add(role + ".persistence", "pass" if persistent else "fail", "persistent_mount" if persistent else "nonpersistent_state", "State and split media need persistent mounts.")
            if mount and not mount.get("RW", False):
                self.add(role + ".mount", "fail", "read_only_mount", "The runtime directory is mounted read-only.")
            try:
                raw = self.exec("botapi", "sh", "-c", STORAGE_METADATA, "doctor", path, user=user)
                lines = raw.decode("ascii").splitlines()
                inode = lines[0]
                fsid, block, blocks, inodes = lines[1].split()
                free_bytes, free_inodes = int(block) * int(blocks), int(inodes)
                uid, gid = int(lines[2]), int(lines[3])
                groups = sorted(set(int(g) for g in lines[4].split()) | {gid})
                if min(free_bytes, free_inodes) < 0 or not re.fullmatch(r"\d+:\d+", inode):
                    raise ValueError
                if lines[5] != "DOCTOR_MOUNTINFO":
                    raise ValueError("mount accounting missing")
                points, quota = mount_accounting(lines[6:], path)
                quota |= bool(self.containers["botapi"].get("HostConfig", {}).get("StorageOpt"))
                self.add(role + ".quota", "unknown" if quota else "pass", "quota_accounting_unverified" if quota else "no_enabled_quota_observed", "Enabled filesystem quotas require separate per-identity headroom accounting.")
                self.storage_data[role] = dict(path=path, mount=mount, filesystem=fsid, inode=inode, mountpoints=points,
                                               available_bytes=free_bytes, available_inodes=free_inodes)
                identity = (uid, gid, groups) == (process["uid"], process["gid"], expected_groups)
                self.add(role + ".identity", "pass" if identity else "unknown", "observed_identity" if identity else "supplementary_groups_mismatch", "Probe and server effective identities compared.")
                if fsid not in filesystems:
                    enough = capacity(free_bytes, free_inodes, self.args.min_free_bytes, self.args.min_free_inodes)
                    self.add(role + ".capacity", "pass" if enough else "fail", "reserve_available" if enough else "insufficient_capacity", "Filesystem reserve policy; Telegram capacity is not guaranteed.", evidence={"available_bytes": free_bytes, "available_inodes": free_inodes, "min_free_bytes": self.args.min_free_bytes, "min_free_inodes": self.args.min_free_inodes})
                    filesystems.add(fsid)
                if self.args.no_write_probe:
                    self.add(role + ".write", "unknown", "write_probe_disabled", "No doctor writes are allowed in this mode.")
                elif not identity:
                    self.add(role + ".write", "unknown", "identity_unverified", "Writing with a different identity would not verify the server.")
                elif self.runner.budget.remaining() < 2:
                    self.add(role + ".write", "unknown", "deadline", "Insufficient budget for a bounded write and cleanup.")
                else:
                    # Container-side timeout remains effective if the host CLI is interrupted.
                    duration = str(max(0.1, min(2.0, self.runner.budget.remaining() - 1)))
                    code, output = self.runner.run(["docker", "exec", "--user", user, self.containers["botapi"]["Id"],
                        "timeout", "-s", "TERM", "-k", "0.5", duration, "sh", "-c", WRITE_PROBE, "doctor", path,
                        str(uid), str(gid), "".join(str(g) + " " for g in expected_groups), __import__("uuid").uuid4().hex])
                    cleanup_bad = b"CLEANUP_FAILED" in output
                    good = code == 0 and output.strip() == b"OK"
                    self.add(role + ".write", "pass" if good else "fail" if cleanup_bad or code in {20, 21, 23, 24, 25} else "unknown",
                             "write_verified" if good else "cleanup_failed" if cleanup_bad else "write_denied" if code == 23 else "write_unverified",
                             "Exclusive probe create/write/unlink under the observed identity.", remediation="Inspect the private directory for this run's .doctor- probe if cleanup could not be confirmed." if not good else "")
            except (RunError, ValueError, IndexError, UnicodeError):
                self.add(role + ".storage", "unknown", "storage_unverified", "Directory, counters or required container utilities could not be verified.")

    def exposure(self):
        from doctor_checks import nginx_config, nginx_routes, overlaps, backing, environment
        api = self.containers.get("botapi", {})
        env = environment(api.get("Config", {}).get("Env"))
        work = (self.process or {}).get("work") or env.get("TELEGRAM_WORK_DIR", "/var/lib/telegram-bot-api")
        temp = (self.process or {}).get("temp") or env.get("TELEGRAM_TEMP_DIR", "/tmp/telegram-bot-api")
        protected = [p for p in (work, temp, (self.process or {}).get('flags', {}).get('log') or env.get("TELEGRAM_LOG_FILE"), env.get("TELEGRAM_API_ID_FILE"), env.get("TELEGRAM_API_HASH_FILE")) if p and p.startswith("/")]
        media = (self.process or {}).get('files') or work
        media_source = backing(media, api.get('Mounts', [])) if media and media != work else None
        sensitive = [backing(p, api.get("Mounts", [])) for p in protected]
        sensitive = [s for s in sensitive if s]
        if self.args.migration_input and os.name == "posix":
            sensitive.append(os.path.abspath(self.args.migration_input))
        # All HTTP-facing components in the selected stack participate in isolation.
        for service, container in self.containers.items():
            if service == "botapi":
                continue
            mounts = container.get("Mounts", [])
            accessible = any(overlaps(m.get("Source", "/"), s) for m in mounts for s in sensitive)
            if accessible:
                self.add("state_mount_accessible", "fail", "state_mount_accessible", "An HTTP component can access a backing of state, temp or secrets, even through a read-only mount.")
            if service != "gateway":
                for mount in mounts:
                    source, target = mount.get('Source'), mount.get('Destination')
                    if source and media_source and overlaps(source, media_source):
                        broad = source == media_source or media_source.startswith(source.rstrip('/') + '/')
                        nested = any(m.get('Destination', '').startswith((target or '').rstrip('/') + '/') for m in mounts if m is not mount)
                        if mount.get('RW') or broad or nested:
                            self.add('media.consumer_mount', 'fail', 'unsafe_media_mount',
                                     'Consumer media must be one scoped read-only subtree without nested mounts.')
                self.add("optional_http_isolation", "unknown", "state_mount_accessible" if accessible else "http_handler_unverified", "Optional HTTP handler semantics require independent isolation evidence outside v1.")
                continue
            try:
                snapshot = self.exec("gateway", "sh", "-c", "nginx -T 2>/dev/null")
                self.nginx_snapshot = hashlib.sha256(snapshot).digest()
                raw = snapshot.decode("utf-8")
                roots, proxies, listens, dynamic = nginx_routes(nginx_config(raw))
                unsafe = any(overlaps(b, s) for root in roots for b in [backing(root, mounts)] if b for s in sensitive)
                if unsafe:
                    self.add("state_exposure", "fail", "state_root_exposed", "HTTP root/alias intersects state, temp or secret storage; read-only and loopback do not make it safe.", remediation="Isolate the HTTP component from state and serve only an authenticated media root (issues #3/#5).")
                elif accessible or dynamic or not sensitive:
                    self.add("state_exposure", "unknown", "state_isolation_unverified", "On-disk nginx config alone cannot establish loaded runtime isolation.")
                else:
                    # Independent lack of a mount to private storage is stronger than a 404.
                    self.add("state_exposure", "pass", "state_mount_isolated", "Gateway has no backing path to private state; supported nginx routes were checked.")
                port = str((self.process or {}).get("port", "8081"))
                expected = "http://botapi:" + port
                compatible = bool(proxies) and all(p.rstrip("/") == expected for p in proxies)
                self.add("gateway_upstream", "pass" if compatible and not dynamic else "unknown" if dynamic else "fail", "upstream_matched" if compatible and not dynamic else "upstream_unverified" if dynamic else "upstream_mismatch", "nginx upstream compared with the observed API listener.")
                _, published_port = self.gateway_endpoint()
                published = int(published_port.split("/", 1)[0]) if published_port else None
                self.add("gateway_listener", "pass" if published in listens else "unknown" if published is None else "fail", "listener_matched" if published in listens else "listener_unverified" if published is None else "port_mismatch", "Published container port compared with nginx listen directives.")
                stat = (self.process or {}).get("flags", {}).get("http-stat-port")
                stats_proxy = any(p.rstrip("/").endswith(":" + str(stat or "8082")) for p in proxies)
                stats_published = bool(stat and api.get("NetworkSettings", {}).get("Ports", {}).get(str(stat) + "/tcp"))
                self.add("statistics_exposure", "fail" if stats_proxy or stats_published else "unknown" if dynamic else "pass", "statistics_exposed" if stats_proxy or stats_published else "statistics_unverified" if dynamic else "not_published", "Statistics routes are inspected without requesting statistics.")
                self.gateway_route_verified = bool(self.process and compatible and not dynamic and published in listens and not stats_proxy and not stats_published)
                # Mount-backed roots could hide symlinks into another mount. Never read their contents.
                for root in roots:
                    if backing(root, mounts):
                        self.add("webroot_symlinks", "unknown", "webroot_symlinks_unverified", "Mounted media roots need independent symlink and nested-mount isolation evidence.")
                        break
            except (RunError, ValueError, UnicodeError):
                self.add("state_exposure", "unknown", "nginx_config_unverified", "Effective nginx includes or runtime isolation could not be verified.")
        if "gateway" not in self.containers:
            self.add("state_exposure", "unknown", "gateway_unavailable", "No selected gateway isolation evidence is available.")


def collect(args, runner, http, checks, images):
    from doctor_checks import check, migration_checks, overlaps, backing, capacity
    checks.extend(migration_checks(args.scenario, args.migration_data))
    if args.input_secure is False:
        checks.append(check("migration.input_privacy", "fail", "unsafe_input_permissions", "Private input requires owner-only POSIX permissions; its contents were not read."))
    elif args.input_secure is None:
        checks.append(check("migration.input_privacy", "unknown", "input_permissions_unverified", "Private input permissions require POSIX verification."))
    installations = [Installation(args, runner, http, checks, images)]
    if args.scenario == "self-to-self":
        explicit_source = any(getattr(args, "source_" + k) for k in ("file", "env_file", "profile", "project_directory", "project_name"))
        if explicit_source:
            installations.append(Installation(args, runner, http, checks, images, source=True))
        else:
            checks.append(check("migration.source_context", "unknown", "missing_source_context", "Self-to-self requires a separately selected source Compose context."))
    for installation in installations:
        for stage in (installation.configuration, installation.runtime, installation.storage, installation.exposure, installation.probes):
            try:
                stage()
            except RunError:
                installation.add(stage.__name__, "unknown", "evidence_unavailable", "This evidence stage could not complete within its limits.")
        local = (installation.process or {}).get("flags", {}).get("local") is True
        installation.add("local_mode", "pass" if local else "unknown" if not installation.process else "fail", "local_mode" if local else "local_mode_unverified", "The observed local server must use local mode.")
    if args.migration_data.get("file_access") in {"local_path", "shared_volume"}:
        checks.append(check("migration.file_mapping", "unknown", "file_mapping_unverified", "Application file-path mapping requires independent observation of the consumer.",
                            remediation="Run tools/check_file_contract.py and verify the consumer mapping independently before migration."))
    if args.scenario == "self-to-self":
        if len(installations) == 2:
            target, source = installations
            server_images = [next((image for image in images if image["role"] == i.role + ".botapi"), {}) for i in installations]
            versions = [image.get("version") for image in server_images]
            revisions = [image.get("labels", {}).get("io.tg-selfhost.bot-api-revision") for image in server_images]
            compatible = bool(all(versions) and versions[0] == versions[1] and (not any(revisions) or all(revisions) and revisions[0] == revisions[1]))
            fresh = args.migration_data.get("transfer", {}).get("method") == "fresh-login"
            checks.append(check("migration.compatibility", "not_applicable" if fresh else "pass" if compatible else "unknown", "fresh_login_no_copy" if fresh else "matching_binary_baseline" if compatible else "compatibility_unverified", "Copy compatibility uses observed binary versions and available source revisions; fresh login does not copy state.", required=not fresh))
            paths = [i.storage_data.get("work", {}) for i in installations]
            backings = [backing(p.get("path", ""), i.containers.get("botapi", {}).get("Mounts", [])) for p, i in zip(paths, installations)]
            inodes = [p.get("inode") for p in paths]
            shared = (all(backings) and overlaps(*backings)) or (all(inodes) and inodes[0] == inodes[1])
            distinct = all(inodes) and not shared
            checks.append(check("migration.state_backing", "fail" if shared else "pass" if distinct else "unknown", "shared_state" if shared else "distinct_state" if distinct else "state_backing_unverified", "Two servers must not share overlapping state backings."))
            measured = None
            method = args.migration_data.get("transfer", {}).get("method")
            component = args.migration_data.get("transfer", {}).get("state_subdir") if method == "per-bot" else "." if method == "dedicated-cold" else None
            if component and target.process and target.storage_data.get("work"):
                try:
                    work = target.storage_data["work"]["path"]
                    destination = target.exec("botapi", "sh", "-c", TARGET_DESTINATION, "doctor", work, component,
                                              user=str(target.process["uid"]) + ":" + str(target.process["gid"]))
                    status = "pass" if destination.strip() == b"EMPTY" else "fail" if destination.strip() == b"OCCUPIED" else "unknown"
                    target.add("transfer_destination", status, "empty_destination" if status == "pass" else "target_state_conflict" if status == "fail" else "destination_unverified", "Copy destination was checked without reading state contents.")
                except RunError:
                    # A failed command may also mean unreadable metadata. Never
                    # infer emptiness from inability to inspect the destination.
                    target.add("transfer_destination", "unknown", "destination_unverified", "Copy destination emptiness could not be verified.")
            if distinct and source.process and component:
                try:
                    work = source.storage_data["work"]["path"]
                    path = work if component == "." else work + "/" + component
                    nested = any((m.get("Destination") == path and component != ".") or m.get("Destination", "").startswith(path.rstrip("/") + "/") for m in source.containers["botapi"].get("Mounts", []))
                    nested |= any(p.startswith(path.rstrip("/") + "/") for p in source.storage_data["work"].get("mountpoints", []))
                    if nested:
                        raise RunError("nested_source_mount")
                    def observe():
                        duration = str(max(0.1, min(2.0, source.runner.budget.remaining() - 1)))
                        return source.exec("botapi", "timeout", "-s", "TERM", "-k", "0.5", duration, "sh", "-c", TRANSFER_METADATA,
                                           "doctor", work, component, user=str(source.process["uid"]) + ":" + str(source.process["gid"]))
                    raw = observe()
                    measured = transfer_metadata(raw)
                    if raw != observe():
                        measured = None
                except (RunError, ValueError, KeyError, UnicodeError):
                    measured = None
            if method == "fresh-login":
                checks.append(check("migration.transfer_capacity", "not_applicable", "fresh_login_no_copy", "Fresh login does not copy local state; baseline storage capacity is still required.", required=False, provenance="derived"))
            elif measured and target.storage_data.get("work"):
                fs = target.storage_data["work"]
                enough = capacity(fs["available_bytes"], fs["available_inodes"], args.min_free_bytes, args.min_free_inodes, *measured)
                checks.append(check("migration.transfer_capacity", "pass" if enough else "fail", "observed_transfer_reserve" if enough else "insufficient_transfer_capacity", "Source metadata plus ten percent and target reserve were compared.", evidence={"count": measured[1]}))
            else:
                checks.append(check("migration.transfer_capacity", "unknown", "transfer_size_unverified", "Declared sizes alone cannot verify target transfer capacity."))
        else:
            checks.append(check("migration.transfer_capacity", "unknown", "source_unverified", "Source storage must be observed before transfer capacity can pass."))
    for installation in installations:
        try:
            installation.unchanged()
        except RunError:
            installation.add("snapshot", "unknown", "runtime_changed", "The final runtime snapshot could not be verified.")


if __name__ == "__main__":
    try:
        if len(sys.argv) != 4 or sys.argv[1] != "--http-worker":
            raise ValueError
        print(json.dumps(http_worker(sys.argv[2], float(sys.argv[3]))))
    except Exception:
        sys.exit(1)
