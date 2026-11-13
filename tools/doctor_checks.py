"""Pure report construction for the doctor preflight."""
from datetime import datetime, timezone
import re
from urllib.parse import quote

STATUSES = {"pass", "fail", "unknown", "not_applicable"}


def redact(value, secrets=()):
    text = str(value)[:4096]
    for secret in sorted((s for s in secrets if isinstance(s, str) and s), key=len, reverse=True):
        for encoded in (secret, quote(secret, safe=""), quote(quote(secret, safe=""), safe="")):
            text = text.replace(encoded, "[redacted]")
    text = re.sub(r"https?://[^\s<>]+", "[endpoint]", text, flags=re.I)
    text = re.sub(r"\d{5,}(?::|%3[aA])[-\w%]{15,}", "[redacted]", text)
    text = re.sub(r"\b[a-fA-F0-9]{32}\b", "[redacted]", text)
    return text


def check(identifier, status, reason_code, message, *, required=True,
          severity="error", provenance="observed", evidence=None, remediation="", secrets=()):
    if (status not in STATUSES or provenance not in {"observed", "derived", "declared"}
            or (status == "not_applicable" and required)):
        raise ValueError("invalid check")
    # Evidence is deliberately restricted to values created by doctor, never raw output.
    allowed = {"count", "available_bytes", "available_inodes", "min_free_bytes", "min_free_inodes"}
    safe = {k: v for k, v in (evidence or {}).items()
            if k in allowed and type(v) is int and 0 <= v <= 2**63 - 1}
    return dict(id=identifier, status=status, required=required, severity=severity,
                reason_code=reason_code, message=redact(message, secrets), evidence=safe,
                provenance=provenance, remediation=redact(remediation, secrets))


def report(scenario, checks, *, error=False, clock=None):
    checks = list(checks)
    if not checks:
        checks.append(check("preflight", "unknown", "evidence_missing", "Required preflight checks have not completed."))
    failed = [c["id"] for c in checks if c["required"] and c["status"] == "fail"]
    unknown = [c["id"] for c in checks if c["required"] and c["status"] in {"unknown", "not_applicable"}]
    code = 2 if error else 1 if failed else 3 if unknown else 0
    verdict = {0: "READY", 1: "BLOCKED", 2: "UNKNOWN", 3: "UNKNOWN"}[code]
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    infrastructure_checks = [c for c in checks if not c["id"].startswith("migration.")]
    def verdict_for(items):
        return "BLOCKED" if any(c["required"] and c["status"] == "fail" for c in items) else "UNKNOWN" if not items or any(c["required"] and c["status"] in {"unknown", "not_applicable"} for c in items) else "READY"
    statuses = {"pass": "PASS", "fail": "FAIL", "unknown": "UNKNOWN", "not_applicable": "SKIP"}
    public_checks = [{"check_id": c["id"], **{k: v for k, v in c.items() if k not in {"id", "status"}},
                      "status": statuses[c["status"]]} for c in checks]
    return {"schema_version": 1, "doctor_version": "0.1.0", "timestamp": now.isoformat(),
            "scenario": scenario, "stage": "preflight", "scope": {"kind": "selected_stack", "contexts": ["source", "target"] if scenario == "self-to-self" else ["source"] if scenario == "self-to-official" else ["target"]},
            "checks": public_checks, "images": [], "infrastructure": {"verdict": verdict_for(infrastructure_checks)},
            "migration": {"verdict": verdict_for([c for c in checks if c["id"].startswith("migration.")]),
                          "pending_actions": pending_actions(scenario), "unverified_session_facts": ["bot_authorization", "session_restrictions", "queue_preservation", "delivery_result"],
            "executor_support": {"manual": "unsupported" if scenario == "hook-only" else "unknown" if scenario is None else "documented_procedure",
                                 "helpers": "not_certified", "bash": "cloud_to_local_only; token-bearing preflight; issues #2/#7/#9",
                                 "browser": "separate tool; issues #6/#8"}},
            "readiness": {"verdict": verdict, "blockers": failed, "unknowns": unknown,
                          "limits": ["Migration execution, bot authorization, queue retention and delivery are not verified.",
                                     "Evidence is a snapshot of the selected stack; opaque external proxies require separate verification."]},
            "exit_code": code}


def render_text(result):
    lines = ["Migration preflight: " + result["readiness"]["verdict"]]
    lines.append("Infrastructure: " + result["infrastructure"]["verdict"])
    lines.append("Migration: " + result["migration"]["verdict"])
    for c in result["checks"]:
        lines.append("{}: {} ({}) - {}".format(c["check_id"], c["status"], c["reason_code"], c["message"]))
        if c["remediation"] and c["status"] in {"FAIL", "UNKNOWN"}:
            lines.append("  Remediation: " + c["remediation"])
    for image in result["images"]:
        lines.append("{}: version={} image_id={}".format(image["role"], image.get("version") or "unknown", image.get("image_id") or "unknown"))
        lines.append("  Registry digests: " + (", ".join(image.get("registry_digests", [])) or "unavailable (local or unknown provenance)"))
    lines.append("Pending actions: " + ", ".join(result["migration"]["pending_actions"]))
    lines.append("Unverified session facts: " + ", ".join(result["migration"]["unverified_session_facts"]))
    lines.append("Executor helpers: " + result["migration"]["executor_support"]["helpers"])
    lines.append("Exit code: " + str(result["exit_code"]))
    return "\n".join(lines)


def environment(value):
    if isinstance(value, dict):
        return {str(k): str(v) if v is not None else "" for k, v in value.items()}
    return dict(item.split("=", 1) for item in (value or []) if isinstance(item, str) and "=" in item)


def valid_port(value):
    return str(value).isdigit() and 1 <= int(value) <= 65535


def settings_checks(env, prefix="target", explicit=False, defaults_known=True):
    findings = []
    if explicit:
        return [check(prefix + ".settings", "unknown", "process_flags_required", "Explicit command requires observed process flags.")]
    for name in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH"):
        direct, file = env.get(name, ""), env.get(name + "_FILE", "")
        status, reason = "pass", "configured"
        if direct and file:
            status, reason = "fail", "conflicting_secret_sources"
        elif not direct and not file:
            status, reason = ("fail", "missing_setting") if defaults_known or name in env or name + "_FILE" in env else ("unknown", "image_defaults_unavailable")
        elif direct and ("..." in direct or "placeholder" in direct.lower() or "<" in direct
                         or (name.endswith("_ID") and (not direct.isdigit() or int(direct) <= 0))):
            status, reason = "fail", "placeholder_setting"
        elif file:
            status, reason = "unknown", "secret_file_unverified"
        findings.append(check(prefix + "." + name.lower(), status, reason, "Credential presence check; Telegram validity is not tested."))
    for name in ("TELEGRAM_WORK_DIR", "TELEGRAM_TEMP_DIR"):
        missing_defaults = name not in env and not defaults_known
        findings.append(check(prefix + "." + name.lower(), "unknown" if missing_defaults else "pass" if env.get(name, "").startswith("/") else "fail",
                              "image_defaults_unavailable" if missing_defaults else "configured" if env.get(name, "").startswith("/") else "missing_setting", "An absolute container directory is required."))
    for name in ("TELEGRAM_LOCAL", "TELEGRAM_STAT"):
        valid = env.get(name, "") in {"", "0", "1", "true", "false", "TRUE", "FALSE"}
        findings.append(check(prefix + "." + name.lower(), "pass" if valid else "fail", "configured" if valid else "invalid_boolean", "Entrypoint boolean syntax check."))
    port = env.get("TELEGRAM_HTTP_PORT", "8081")
    findings.append(check(prefix + ".http_port", "pass" if valid_port(port) else "fail", "configured" if valid_port(port) else "invalid_port", "HTTP port must be between 1 and 65535."))
    if valid_port(port) and int(port) in {8082, 8090}:
        findings.append(check(prefix + ".stat_port", "fail", "port_conflict", "Statistics and API listeners conflict."))
    return findings


def runtime_identity(container):
    state = container.get("State", {})
    return (container.get("Id"), container.get("Image"), state.get("Pid"), state.get("StartedAt"), state.get("Running"),
            container.get("RestartCount"), state.get("Health", {}).get("Status"), state.get("Restarting"), state.get("Paused"), state.get("Dead"), container.get("Config"),
            container.get("HostConfig"), container.get("Mounts"), container.get("NetworkSettings"))


def container_state(container):
    state = container.get("State", {})
    if state.get("Running") is not True:
        return "fail", "service_stopped"
    for flag in ("Paused", "Restarting", "Dead"):
        if state.get(flag):
            return "fail", "service_" + flag.lower()
    health = state.get("Health", {}).get("Status")
    if health == "unhealthy":
        return "fail", "service_unhealthy"
    if health and health != "healthy":
        return "unknown", "health_pending"
    return "pass", "running"


def root_response(status, content_type, body):
    import json
    if len(body) > 16384 or status != 404 or content_type.split(";", 1)[0].strip().lower() != "application/json":
        return False
    try:
        payload = json.loads(body)
        return (isinstance(payload, dict) and payload.get("ok") is False
                and type(payload.get("error_code")) is int and payload["error_code"] == 404)
    except (ValueError, UnicodeError):
        return False


def process_flags(argv):
    """Accept only the observed official long-option convention."""
    flags = {}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if not arg.startswith("--"):
            raise ValueError("unsupported process arguments")
        key, sep, value = arg[2:].partition("=")
        if not sep and key != "local":
            i += 1
            if i >= len(argv) or argv[i].startswith("--"):
                raise ValueError("missing process argument")
            value = argv[i]
        if key in flags:
            raise ValueError("duplicate process argument")
        flags[key] = True if key == "local" and not sep else value
        i += 1
    return flags


def mount_for(path, mounts):
    import posixpath
    if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
        return None
    path = posixpath.normpath(path)
    matches = [m for m in mounts if path == m.get("Destination") or path.startswith(m.get("Destination", "").rstrip("/") + "/")]
    return max(matches, key=lambda m: len(m.get("Destination", "")), default=None)


def capacity(available_bytes, available_inodes, reserve_bytes, reserve_inodes, transfer_bytes=0, transfer_entries=0):
    return (available_bytes >= reserve_bytes + (transfer_bytes * 11 + 9) // 10
            and available_inodes >= reserve_inodes + (transfer_entries * 11 + 9) // 10)


def nginx_tree(text):
    """Parse balanced nginx directives, including quoted values; never evaluate them."""
    import shlex
    lexer = shlex.shlex(text, posix=True, punctuation_chars="{};")
    lexer.whitespace_split = True
    lexer.commenters = "#"
    tokens = []
    for token in lexer:
        tokens.extend(list(token) if token and all(c in "{};" for c in token) else [token])
        if len(tokens) > 50000:
            raise ValueError("nginx token limit")
    index = 0
    def block(depth=0):
        nonlocal index
        if depth > 32:
            raise ValueError("nginx nesting limit")
        result, words = [], []
        while index < len(tokens):
            token = tokens[index]
            index += 1
            if token == "}":
                if words or depth == 0:
                    raise ValueError("unbalanced nginx")
                return result
            if token == ";":
                if not words:
                    raise ValueError("empty nginx directive")
                result.append((words[0], words[1:], []))
                words = []
            elif token == "{":
                if not words:
                    raise ValueError("missing nginx block")
                result.append((words[0], words[1:], block(depth + 1)))
                words = []
            else:
                words.append(token)
        if words or depth:
            raise ValueError("unbalanced nginx")
        return result
    return block()


def nginx_config(text):
    import fnmatch
    markers = list(re.finditer(r"(?m)^# configuration file ([^\r\n]+):\r?$", text))
    if not markers:
        tree = nginx_tree(text)
        def has_include(nodes):
            return any(name == "include" or has_include(children) for name, args, children in nodes)
        if has_include(tree):
            raise ValueError("unresolved include")
        return tree
    if len(markers) > 64:
        raise ValueError("nginx include limit")
    files = {m.group(1): text[m.end():markers[i + 1].start() if i + 1 < len(markers) else len(text)]
             for i, m in enumerate(markers)}
    if len(files) != len(markers):
        raise ValueError("ambiguous nginx dump")
    expanded = 0
    def expand(path, seen):
        if path in seen or len(seen) > 32:
            raise ValueError("recursive include")
        def visit(nodes):
            nonlocal expanded
            result = []
            for name, args, children in nodes:
                expanded += 1
                if expanded > 50000:
                    raise ValueError("expanded nginx limit")
                if name == "include":
                    if len(args) != 1 or "$" in args[0]:
                        raise ValueError("dynamic include")
                    pattern = args[0] if args[0].startswith("/") else "/etc/nginx/" + args[0]
                    matches = [p for p in files if fnmatch.fnmatchcase(p, pattern)]
                    if not matches:
                        raise ValueError("unresolved include")
                    for matched in matches:
                        result.extend(expand(matched, seen | {path}))
                else:
                    result.append((name, args, visit(children)))
            return result
        return visit(nginx_tree(files[path]))
    return expand(markers[0].group(1), set())


def nginx_routes(tree):
    roots, proxies, listens, unknown = [], [], [], False
    safe = {"events", "worker_connections", "http", "server", "location", "upstream", "user", "worker_processes", "pid",
            "error_log", "access_log", "log_format", "default_type", "types", "sendfile", "keepalive_timeout", "tcp_nopush",
            "gzip", "index", "server_name", "proxy_http_version", "proxy_set_header", "client_max_body_size", "autoindex",
            "resolver", "proxy_read_timeout", "proxy_connect_timeout", "proxy_send_timeout", "proxy_buffering", "charset",
            "client_body_timeout", "client_body_temp_path", "client_header_timeout", "proxy_request_buffering",
            "limit_req_zone", "limit_conn_zone", "limit_req", "limit_req_status", "limit_conn", "limit_conn_status"}
    def walk(nodes, in_types=False):
        nonlocal unknown
        for name, args, children in nodes:
            if name == "map":
                # Unknown maps never constitute routing/privacy evidence.
                supported = (args == ["$request_method", "$privacy_method"] and children == [
                    ('default',['OTHER'],[]),('GET',['GET'],[]),('POST',['POST'],[]),
                    ('HEAD',['HEAD'],[]),('OPTIONS',['OPTIONS'],[])]) or (
                    args == ["$uri", "$privacy_route"] and children == [
                    ('default',['other'],[]),('~^/bot[^/]+/',['api'],[]),('~^/file/bot[^/]+/',['file'],[])])
                # Only the shipped URI redaction map is understood. Its entries
                # are logging values, never nested routing directives.
                supported |= (args == ["$uri", "$uri_redacted"] and bool(children)
                             and all(not nested and len(values) == 1
                                     and (key == "default" or key.startswith("~"))
                                     for key, values, nested in children))
                supported |= (args == ["$request_uri", "$legacy_file_request"] and children == [
                    ("default", ["0"], []), (r"~^/file(?:/|%2[fF]|%25|\?|$)", ["1"], [])])
                supported |= (args == ['$server_port', '$upload_global_key'] and children == [('default', ['uploads'], [])])
                supported |= (args == ['$server_port:$http_transfer_encoding', '$reject_public_chunked'] and children == [
                    ('default', ['0'], []), ('~*^80:.+', ['1'], [])])
                supported |= (args == ['$request_method:$http_content_length:$http_transfer_encoding', '$reject_get_body'] and children == [
                    ('default', ['0'], []), ('~*^(GET|HEAD):0*[1-9][0-9]*:', ['1'], []),
                    ('~*^(GET|HEAD):[^:]*:.+', ['1'], [])])
                unknown |= not supported
                continue
            if name in {"root", "alias"}:
                if len(args) != 1 or "$" in args[0] or not args[0].startswith("/"):
                    unknown = True
                else:
                    roots.append(args[0])
            elif name == 'set':
                if len(args) != 2 or not ((args[0] == '$botapi_upstream' and re.fullmatch(r'http://botapi:[0-9]+', args[1])) or args == ['$observer_upstream', 'http://botapi:8090']):
                    unknown = True
            elif name == 'if':
                if not ((args == ['($legacy_file_request)'] and children == [('return', ['404'], [])]) or
                        (args == ['($reject_public_chunked)'] and children == [('return', ['411'], [])]) or
                        (args == ['($reject_get_body)'] and children == [('return', ['400'], [])]) or
                        (args in [['($args)'], ['($http_content_length)'], ['($http_transfer_encoding)']] and children == [('return', ['400'], [])])):
                    unknown = True
                continue
            elif name == 'limit_except':
                if args not in (['GET'], ['GET', 'POST']) or children != [('deny', ['all'], [])]: unknown = True
                continue
            elif name == 'return':
                if children or args not in [['404'], ['503', '{"error":"observer_unavailable"}'], ['404', '{"error":"not_found"}']]: unknown = True
                continue
            elif name == 'proxy_pass_request_body':
                unknown |= args != ['off']
            elif name == 'proxy_intercept_errors':
                unknown |= args != ['on']
            elif name == 'error_page':
                unknown |= args != ['502', '504', '=503', '@unavailable']
            elif name == "proxy_pass":
                if args == ['$botapi_upstream$request_uri']:
                    targets = [a[1] for n, a, _ in flatten_nginx(tree) if n == 'set' and len(a) == 2 and a[0] == '$botapi_upstream']
                    if len(targets) != 1: unknown = True
                    else: proxies.append(targets[0])
                elif args == ['$observer_upstream$uri']:
                    proxies.append('http://botapi:8090')
                elif len(args) != 1 or not re.fullmatch(r"http://[a-zA-Z0-9_.-]+:[0-9]+/?", args[0]):
                    unknown = True
                else:
                    proxies.append(args[0])
            elif name == "listen":
                if not args:
                    unknown = True
                else:
                    port = args[0].rsplit(":", 1)[-1]
                    if valid_port(port):
                        listens.append(int(port))
                    else:
                        unknown = True
            elif name not in safe and not in_types:
                unknown = True
            walk(children, in_types or name == "types")
    walk(tree)
    return roots, proxies, listens, unknown


def nginx_privacy(tree):
    """Recognize only the shipped policy across all effective contexts."""
    errors=[]; accesses=[]; formats=[]; maps=[]
    def visit(nodes):
        for name,args,children in nodes:
            if name=='error_log': errors.append(args)
            if name=='access_log': accesses.append(args)
            if name=='log_format': formats.append(args)
            if name=='map': maps.append((name,args,children))
            if name!='map': visit(children)
    visit(tree)
    root_null=any(name=='error_log' and args==['/dev/null'] for name,args,_ in tree)
    return (root_null and bool(errors) and all(args==['/dev/null'] for args in errors)
            and bool(accesses) and all(args in (['/var/log/nginx/access.log','privacy'], ['off']) for args in accesses)
            and formats==[['privacy','$privacy_method $privacy_route $status $body_bytes_sent $request_time']]
            and not nginx_routes(maps)[-1]
            and {tuple(args) for _,args,_ in maps} in (
                {('$request_method','$privacy_method'),('$uri','$privacy_route')},
                {('$request_method','$privacy_method'),('$uri','$privacy_route'),('$request_uri','$legacy_file_request')},
                {('$request_method','$privacy_method'),('$uri','$privacy_route'),('$request_uri','$legacy_file_request'),
                 ('$server_port','$upload_global_key'),('$server_port:$http_transfer_encoding','$reject_public_chunked'),
                 ('$request_method:$http_content_length:$http_transfer_encoding','$reject_get_body')})
            and len(maps) == len({tuple(args) for _,args,_ in maps}))

def flatten_nginx(nodes):
    for node in nodes:
        yield node
        yield from flatten_nginx(node[2])


def nginx_route_contract(tree, api_port):
    """Match listeners, exact paths and fixed variable targets as one recipe."""
    _, proxies, listens, unknown = nginx_routes(tree)
    expected = 'http://botapi:' + str(api_port)
    if unknown: return False
    if 81 not in listens:
        return bool(proxies) and all(p.rstrip('/') == expected for p in proxies)
    servers = [children for name, _, children in flatten_nginx(tree) if name == 'server']
    resolvers = [args for name,args,_ in flatten_nginx(tree) if name == 'resolver']
    if resolvers != [['127.0.0.11', 'valid=5s', 'ipv6=off']]: return False
    if len(proxies) != 6: return False
    if len(servers) != 2: return False
    for nodes in servers:
        ports = [args for name, args, _ in nodes if name == 'listen']
        locations = {tuple(args): children for name, args, children in nodes if name == 'location'}
        all_locations = [1 for name, _, _ in nodes if name == 'location']
        if len(locations) != len(all_locations): return False
        if ports == [['80'], ['82']]:
            if ('set', ['$botapi_upstream', expected], []) not in nodes: return False
            if ('if', ['($legacy_file_request)'], [('return', ['404'], [])]) not in nodes: return False
            fixed = {('=', '/health/live'), ('=', '/health/ready'), ('=', '/status'), ('=', '/selfz'), ('=', '/file'), ('/file/',)}
            regex = [path for path in locations if len(path) == 2 and path[0] == '~*']
            if len(regex) != 2 or set(locations) != fixed | {('/',)} | set(regex): return False
            if any(locations[path] != [('return', ['404'], [])] for path in fixed): return False
            upload = next((path for path in regex if re.fullmatch(
                r'\^/bot\[\^/\]\+/\(\?:sendPhoto(?:\|[A-Za-z][A-Za-z0-9]*)+\)\(\?:/\|\$\)', path[1])), None)
            polling = ('~*', '^/bot[^/]+/getUpdates$')
            if upload is None or polling not in regex: return False
            for path in [('/',), upload, polling]:
                children = locations[path]
                if ('limit_except', ['GET', 'POST'], [('deny', ['all'], [])]) not in children: return False
                routes = [args for name,args,_ in flatten_nginx(children) if name == 'proxy_pass']
                if routes != [['$botapi_upstream$request_uri']]: return False
        elif ports == [['81']]:
            if ('set', ['$observer_upstream', 'http://botapi:8090'], []) not in nodes: return False
            exact = {('=', '/health/live'), ('=', '/health/ready'), ('=', '/status')}
            if set(locations) != exact | {('/',), ('@unavailable',)}: return False
            for path in exact:
                if locations[path] != [('limit_except', ['GET'], [('deny', ['all'], [])]), ('proxy_pass', ['$observer_upstream$uri'], [])]: return False
            required = [('proxy_pass_request_body', ['off'], []), ('proxy_set_header', ['Authorization', ''], []),
                        ('proxy_set_header', ['Content-Length', ''], []), ('proxy_set_header', ['Cookie', ''], []),
                        ('proxy_set_header', ['Host', 'localhost'], []), ('proxy_intercept_errors', ['on'], []),
                        ('error_page', ['502', '504', '=503', '@unavailable'], []),
                        ('proxy_connect_timeout', ['1s'], []), ('proxy_read_timeout', ['3s'], []), ('access_log', ['off'], [])]
            if any(node not in nodes for node in required): return False
            for condition in ['($args)', '($http_content_length)', '($http_transfer_encoding)']:
                if ('if', [condition], [('return', ['400'], [])]) not in nodes: return False
            if locations[('/',)] != [('return', ['404', '{"error":"not_found"}'], [])]: return False
            if locations[('@unavailable',)] != [('return', ['503', '{"error":"observer_unavailable"}'], [])]: return False
        else: return False
    # Nested overrides must not change either fixed target or escape route context.
    sets = [(args[0], args[1]) for name,args,_ in flatten_nginx(tree) if name == 'set']
    return sorted(sets) == sorted([('$botapi_upstream', expected), ('$observer_upstream', 'http://botapi:8090')])


def overlaps(a, b):
    import posixpath
    a, b = posixpath.normpath(a), posixpath.normpath(b)
    return a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/")


def backing(path, mounts):
    import posixpath
    mount = mount_for(path, mounts)
    if not mount or not mount.get("Source"):
        return None
    return posixpath.normpath(mount["Source"] + "/" + posixpath.relpath(path, mount["Destination"]))


def media_conflicts(media, private, mounts):
    """Compare both namespace paths and their resolved Docker backings."""
    if not media or not private or not all(isinstance(p, str) and p.startswith('/') for p in [media, *private]):
        return None
    source = backing(media, mounts)
    return any(overlaps(media, p) or (source and backing(p, mounts)
               and overlaps(source, backing(p, mounts))) for p in private)


INPUT_BOOLS = {"workflow_prepared", "webhook_profile_prepared", "drop_pending_updates", "source_backup_prepared"}


def state_component(value):
    return (isinstance(value, str) and 0 < len(value.encode("utf-8")) <= 255
            and value not in {".", ".."} and not any(c in value for c in "/\\")
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def validate_migration_input(data):
    if not isinstance(data, dict) or set(data) - (INPUT_BOOLS | {"schema_version", "delivery_action", "file_access", "transfer", "transfer_metadata", "source_backlog_policy"}):
        raise ValueError("invalid input fields")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("invalid schema version")
    for k in INPUT_BOOLS & data.keys():
        if type(data[k]) is not bool:
            raise ValueError("invalid boolean")
    for k, values in (("file_access", {"not_used", "local_path", "shared_volume", "remote_authenticated"}),
                      ("delivery_action", {"preserve", "set", "polling"}),
                      ("source_backlog_policy", {"drain", "accept-loss"})):
        if k in data and (not isinstance(data[k], str) or data[k] not in values):
            raise ValueError("invalid choice")
    if "transfer" in data:
        transfer = data["transfer"]
        if not isinstance(transfer, dict) or set(transfer) - {"method", "state_subdir", "backup_prepared", "exclusive_use_plan_prepared", "backlog_policy", "dedicated_source", "target_empty_prepared"}:
            raise ValueError("invalid transfer")
        if "state_subdir" in transfer and not state_component(transfer["state_subdir"]):
            raise ValueError("invalid state component")
        if any(type(transfer[k]) is not bool for k in ("backup_prepared", "exclusive_use_plan_prepared", "dedicated_source", "target_empty_prepared") if k in transfer):
            raise ValueError("invalid transfer boolean")
        for key, choices in (("method", {"per-bot", "dedicated-cold", "fresh-login"}),
                             ("backlog_policy", {"drain", "accept-loss"})):
            if key in transfer and (not isinstance(transfer[key], str) or transfer[key] not in choices):
                raise ValueError("invalid transfer choice")
        if transfer.get("method") in {"dedicated-cold", "fresh-login"} and "state_subdir" in transfer:
            raise ValueError("state subtree is only used for per-bot transfer")
    if "transfer_metadata" in data:
        metadata = data["transfer_metadata"]
        if not isinstance(metadata, dict) or set(metadata) - {"bytes", "entries"} or any(type(v) is not int or v < 0 or v > 2**63 - 1 for v in metadata.values()):
            raise ValueError("invalid transfer metadata")
    return data


def pending_actions(scenario):
    return {"official-to-self": ["stop_application", "backup", "logOut_cloud", "authorize_target", "switch_endpoint", "apply_delivery_decision"],
            "self-to-self": ["stop_application", "backup", "detach_or_logout_for_selected_method", "stop_all_required_writers", "verify_consistency_at_transfer_boundary", "transfer_or_fresh_login", "switch_endpoint", "apply_delivery_decision"],
            "self-to-official": ["stop_application", "backup", "logOut_source", "authorize_cloud", "switch_endpoint", "apply_delivery_decision"]}.get(scenario, [])


def migration_checks(scenario, data):
    result = []
    def add(key, value, reason="prerequisite_declared"):
        status = "unknown" if value is None else "pass" if value is True else "fail"
        result.append(check("migration." + key, status, "missing_prerequisite" if value is None else reason if value else "prerequisite_rejected",
                            "Missing prerequisite: " + key if value is None else "Declared prerequisite: " + key + "; this is not an execution receipt.", provenance="declared",
                            remediation="Prepare the private input field: " + key if value is None or value is False else ""))
    if scenario == "hook-only":
        return [check("migration.scenario", "fail", "unsupported_scenario", "Webhook-only actions are outside server migration; see issues #7/#9.")]
    add("schema_version", True if data.get("schema_version") == 1 else None)
    add("workflow_prepared", data.get("workflow_prepared"))
    access = data.get("file_access")
    if access == "remote_authenticated":
        result.append(check("migration.file_access", "unknown", "file_contract_unverified", "Remote authenticated file access requires an independently verified contract at the boundary of issue #5.",
                            provenance="declared", remediation="Run tools/check_file_contract.py independently; doctor does not certify remote auth from a declaration or receipt."))
    else:
        add("file_access", True if access else None)
    # False is a valid explicit queue decision, not a rejected plan.
    add("drop_pending_updates", "drop_pending_updates" in data or None)
    action = data.get("delivery_action")
    add("delivery_action", True if action else None)
    if action in {"preserve", "set"}:
        add("webhook_profile_prepared", data.get("webhook_profile_prepared"))
    if scenario == "self-to-official":
        add("source_backup_prepared", data.get("source_backup_prepared"))
        add("source_backlog_policy", True if data.get("source_backlog_policy") else None)
    if scenario == "self-to-self":
        transfer = data.get("transfer", {})
        method = transfer.get("method")
        add("transfer.method", True if method else None)
        if method == "per-bot":
            add("transfer.state_subdir", True if transfer.get("state_subdir") else None)
        elif method in {"dedicated-cold", "fresh-login"}:
            result.append(check("migration.transfer.state_subdir", "not_applicable", "not_applicable", "No per-bot subtree is selected for this method.", required=False, provenance="derived"))
        for field in ("backup_prepared", "exclusive_use_plan_prepared"):
            add("transfer." + field, transfer.get(field))
        policy = transfer.get("backlog_policy")
        add("transfer.backlog_policy", (policy == "accept-loss") if method == "fresh-login" and policy else True if policy else None)
        if method == "dedicated-cold":
            for field in ("dedicated_source", "target_empty_prepared"):
                add("transfer." + field, transfer.get(field))
    return result
