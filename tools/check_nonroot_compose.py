"""Validate real Compose models and prepared sources; no daemon on import."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
WORK = "/var/lib/telegram-bot-api"
TEMP = "/tmp/telegram-bot-api"
MEDIA = "/var/lib/telegram-bot-api-files"
LABEL = "io.tg-selfhost.nonroot-check"


class CheckError(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise CheckError(code)


def identity(value):
    require(bool(re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", value or "")), "invalid_numeric_identity")
    require(all(int(v) <= 2147483647 for v in value.split(":")), "identity_out_of_range")
    return tuple(map(int, value.split(":")))


def overlaps(a, b):
    a, b = a.rstrip("/"), b.rstrip("/")
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def validate_effective_mounts(mounts):
    storage = [m for m in mounts if m.get("Destination") in (WORK, TEMP, MEDIA)]
    require(len(storage) >= 2, "effective_storage_missing")
    require(len({m["Destination"] for m in storage}) == len(storage), "effective_storage_duplicate")
    for index, mount in enumerate(storage):
        for other in storage[index + 1:]:
            require(not overlaps(mount["Source"], other["Source"]), "effective_backing_alias")


def validate_download_layout(temporary, final, mounts):
    """A download rename must remain inside the same media mount."""
    def backing(path):
        matches = [m for m in mounts if path.startswith(m['Destination'].rstrip('/') + '/')]
        require(bool(matches), 'download_mount_missing')
        return max(matches, key=lambda m: len(m['Destination']))['Destination']
    require(backing(temporary) == backing(final) == MEDIA, 'download_cross_mount_layout')


def validate_reader_model(model, image=None, volume_name=None):
    for role in ("reader", "posix", "stranger"):
        service = model["services"][role]
        if image is not None:
            require(service.get("image") == image, "reader_candidate_mismatch")
        require(service.get("user") == "2001:3000" and service.get("network_mode") == "none", "reader_identity_or_network")
        require(not service.get('privileged') and not service.get('cap_add') and not service.get('devices')
                and not service.get('pid') and not service.get('ipc'), 'reader_host_privileges')
        groups = list(map(str, service.get("group_add", [])))
        require(groups == (["2000"] if role != "stranger" else []), "reader_group_contract")
        mounts = service.get("volumes", [])
        require(len(mounts) == 1, "reader_mount_scope")
        mount = mounts[0]
        require(mount.get("target") == "/media/documents" and mount.get("read_only", False) is (role != 'posix')
                and mount.get("type") == "volume" and mount.get("source") == "media"
                and mount.get("volume", {}).get("subpath") == "synthetic-bot/documents", "reader_subtree_contract")
    if volume_name is not None:
        volume = model["volumes"]["media"]
        require(volume.get("external") is True and volume.get("name") == volume_name, "reader_backing_mismatch")


def validate_model(model, layers, env, check_sources=True):
    """Validate effective Compose JSON, never a hand-merged copy of YAML."""
    services = model["services"]
    bot = services["botapi"]
    split = "files" in layers
    custom = "nonroot" in layers
    require(not split or custom, "media_requires_nonroot_layer")
    if custom:
        expected = f"{env.get('BOTAPI_UID', '')}:{env.get('BOTAPI_GID', '')}"
        identity(expected)
        require(bot.get("user") == expected, "compose_identity_mismatch")
    mounts = bot.get("volumes", [])
    targets = [m["target"] for m in mounts]
    require(len(targets) == len(set(targets)), "duplicate_storage_target")
    roots = [WORK, TEMP] if custom else [WORK]
    if split:
        roots.append(MEDIA)
        settings = bot.get("environment", {})
        require(settings.get("TELEGRAM_FILES_DIR") == MEDIA, "missing_files_dir")
        require(settings.get("BOTAPI_MEDIA_REQUIRE_NONROOT") == "1"
                and settings.get("BOTAPI_MEDIA_EXPECTED_UID") == env["BOTAPI_UID"]
                and settings.get("BOTAPI_MEDIA_EXPECTED_GID") == env["BOTAPI_GID"], "media_identity_guard")
    sources = []
    for target in roots:
        matches = [m for m in mounts if m["target"] == target]
        require(len(matches) == 1, "missing_storage_mount")
        mount = matches[0]
        if mount.get("type") == "bind":
            sources.append(Path(mount["source"]).resolve())
        if custom:
            require(mount.get("type") == "bind" and not mount.get("read_only", False), "storage_bind_required")
            require(mount.get("bind", {}).get("create_host_path") is False, "implicit_source_creation")
            source = Path(mount["source"])
            if check_sources:
                require(source.is_dir() and source.is_absolute(), "unprepared_source")
                require(not any(p.is_symlink() for p in (source, *source.parents)), "symlink_source")
    for index, source in enumerate(sources):
        for other in sources[index + 1:]:
            require(not (source == other or source in other.parents or other in source.parents), "storage_source_alias")
            if check_sources:
                require(not os.path.samefile(source, other), "storage_inode_alias")
    for mount in services.get("gateway", {}).get("volumes", []):
        require(not any(overlaps(mount["target"], target) for target in (WORK, TEMP, MEDIA)), "gateway_storage_exposure")
        if mount.get("source"):
            gateway_source = Path(mount["source"]).resolve()
            require(not any(gateway_source == s or gateway_source in s.parents or s in gateway_source.parents
                            for s in sources), "gateway_backing_exposure")
    return True


class Commands:
    def __init__(self, deadline=1200):
        self.until = time.monotonic() + deadline

    def run(self, args, timeout=60, env=None, check=True):
        remaining = self.until - time.monotonic()
        require(remaining > 0, "acceptance_deadline")
        try:
            result = subprocess.run(["docker", *args], capture_output=True, text=True,
                                    env=env, timeout=min(timeout, remaining))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CheckError("docker_unavailable_or_deadline") from exc
        if check:
            require(result.returncode == 0, "docker_operation_failed")
        return result


def compose_matrix(commands):
    with tempfile.TemporaryDirectory(prefix="botapi-compose-") as directory:
        directory = Path(directory)
        envfile = directory / "empty.env"
        envfile.write_text("", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("BOTAPI_", "API_", "COMPOSE_"))}
        from image_inputs import public_environment, resolve
        env.update(public_environment(resolve()))
        env.update(API_ID="12345", API_HASH="synthetic-placeholder", BOTAPI_UID="1000", BOTAPI_GID="2000")
        for role in ("STATE", "TEMP", "MEDIA"):
            source = directory / role.lower()
            source.mkdir()
            env[f"BOTAPI_{role}_SOURCE"] = str(source)
        def config(layers, settings):
            args = ["compose", "--env-file", str(envfile), "--project-directory", str(ROOT),
                    "-f", str(ROOT / "docker-compose.yml")]
            for layer in layers:
                args += ["-f", str(ROOT / f"docker-compose.{layer}.yml")]
            return commands.run([*args, "config", "--format", "json"], env=settings, check=False)
        for layers in ((), ("build",), ("nonroot",), ("nonroot", "build"),
                       ("nonroot", "files"), ("nonroot", "files", "build")):
            result = config(layers, env)
            require(result.returncode == 0, "compose_merge_failed")
            validate_model(json.loads(result.stdout), layers, env)
        for variable in ("BOTAPI_UID", "BOTAPI_GID", "BOTAPI_STATE_SOURCE", "BOTAPI_TEMP_SOURCE", "BOTAPI_MEDIA_SOURCE"):
            for value in (None, ""):
                settings = dict(env)
                if value is None:
                    settings.pop(variable)
                else:
                    settings[variable] = value
                layers = ("nonroot", "files") if variable == "BOTAPI_MEDIA_SOURCE" else ("nonroot",)
                require(config(layers, settings).returncode != 0, "compose_required_input_accepted")
        for key, value in (("BOTAPI_UID", "abc"), ("BOTAPI_GID", "-1"), ("BOTAPI_UID", "0"),
                           ("BOTAPI_MEDIA_SOURCE", env["BOTAPI_STATE_SOURCE"])):
            settings = {**env, key: value}
            result = config(("nonroot", "files"), settings)
            if result.returncode == 0:
                try:
                    validate_model(json.loads(result.stdout), ("nonroot", "files"), settings)
                except CheckError:
                    pass
                else:
                    raise CheckError("invalid_compose_contract_accepted")
        settings = {k: v for k, v in env.items() if k not in ("BOTAPI_UID", "BOTAPI_GID")}
        require(config(("files",), settings).returncode != 0, "media_without_identity_accepted")
        # Compose cannot infer which earlier file supplied user. Enforce the
        # supported layer contract explicitly even when all variables are set.
        result = config(("files",), env)
        if result.returncode == 0:
            try:
                validate_model(json.loads(result.stdout), ("files",), env)
            except CheckError:
                pass
            else:
                raise CheckError("media_without_layer_accepted")
        # Missing roots and symlink aliases are rejected without provisioning.
        settings = {**env, "BOTAPI_TEMP_SOURCE": str(directory / "absent")}
        result = config(("nonroot",), settings)
        require(result.returncode == 0, "missing_source_model_unavailable")
        try:
            validate_model(json.loads(result.stdout), ("nonroot",), settings)
        except CheckError:
            require(not (directory / "absent").exists(), "checker_created_missing_source")
        else:
            raise CheckError("missing_source_accepted")
        if os.name == "posix":
            alias = directory / "alias"
            alias.symlink_to(directory / "state", target_is_directory=True)
            settings = {**env, "BOTAPI_MEDIA_SOURCE": str(alias)}
            result = config(("nonroot", "files"), settings)
            require(result.returncode == 0, "alias_model_unavailable")
            try:
                validate_model(json.loads(result.stdout), ("nonroot", "files"), settings)
            except CheckError:
                pass
            else:
                raise CheckError("symlink_source_accepted")
    print("PASS compose models and required inputs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deadline", type=int, default=120)
    args = parser.parse_args()
    require(1 <= args.deadline <= 1800, "invalid_deadline")
    compose_matrix(Commands(args.deadline))


if __name__ == "__main__":
    try:
        main()
    except (CheckError, KeyError, ValueError, OSError):
        print("FAIL nonroot Compose contract")
        raise SystemExit(1)
