#!/usr/bin/env python3
"""Token-free installation and migration preflight."""
import argparse
import json
import sys
sys.dont_write_bytecode = True
import time
from doctor_checks import check, report, render_text
from doctor_runtime import Budget, Runner, Http, collect, RunError, CapabilityError, endpoint, load_migration_input


class InvalidInput(ValueError):
    """Only invocation and private-input failures use exit code 2."""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InvalidInput("invalid invocation")


def positive(value):
    try:
        number = float(value)
        if not 0 < number < float("inf"):
            raise ValueError
        return number
    except ValueError:
        raise argparse.ArgumentTypeError("positive number required") from None


def positive_integer(value):
    try:
        if not value.isascii() or not value.isdigit() or int(value) <= 0:
            raise ValueError
        return int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("positive integer required")


def parser():
    p = Parser(description="Inspect migration prerequisites without contacting bots", allow_abbrev=False)
    p.add_argument("--scenario", required=True, choices=("official-to-self", "self-to-self", "self-to-official", "hook-only"))
    p.add_argument("--format", choices=("text", "json"), default="text")
    for prefix in ("", "source-"):
        for name in ("file", "profile", "env-file"):
            flags = ["--" + prefix + name]
            if not prefix and name == "file":
                flags.insert(0, "-f")
            p.add_argument(*flags, action="append")
        for name in ("project-directory", "project-name"):
            flags = ["--" + prefix + name]
            if not prefix and name == "project-name":
                flags.insert(0, "-p")
            p.add_argument(*flags)
    for name in ("gateway-url", "source-gateway-url", "migration-input"):
        p.add_argument("--" + name)
    p.add_argument("--no-write-probe", action="store_true")
    for name, default in (("timeout", 5), ("deadline", 60)):
        p.add_argument("--" + name, type=positive, default=default)
    for name, default in (("min-free-bytes", 1073741824), ("min-free-inodes", 1024)):
        p.add_argument("--" + name, type=positive_integer, default=default)
    return p


def main(argv=None, *, runner=None, http=None, clock=time.monotonic, collector=collect):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_mode = any(arg == "--format=json" or (arg == "--format" and i + 1 < len(argv) and argv[i + 1] == "json") for i, arg in enumerate(argv))
    checks, images, scenario = [], [], None
    try:
        args = parser().parse_args(argv)
        scenario = args.scenario
        try:
            args.migration_data, args.input_secure = load_migration_input(args.migration_input)
            for url in (args.gateway_url, args.source_gateway_url):
                if url:
                    endpoint(url)
        except (ValueError, OSError):
            raise InvalidInput("invalid private input or endpoint") from None
        runner = runner or Runner(budget=Budget(args.timeout, args.deadline, clock))
        http = http or Http(runner)
        collector(args, runner, http, checks, images)
        result = report(scenario, checks)
        result["images"] = images
        json_mode = args.format == "json"
    except RunError as error:
        reason = str(error) if str(error) in {"deadline", "timeout", "overflow", "unavailable"} else "runtime_unavailable"
        checks.append(check("runtime_collection", "unknown", reason, "Evidence collection could not finish."))
        result = report(scenario, checks)
    except (InvalidInput, CapabilityError):
        checks.append(check("invocation", "unknown", "invalid_input", "Invalid invocation, private input or Compose JSON capability."))
        result = report(scenario, checks, error=True)
    except Exception:
        checks.append(check("internal_error", "unknown", "internal_error", "Evidence collection encountered an internal error."))
        result = report(scenario, checks)
    result["images"] = images
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")) if json_mode else render_text(result))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
