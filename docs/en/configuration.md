---
title: Configuration
translation: /docs/ru/configuration.html
---

# Configuration

## Doctor configuration checks

Doctor delegates interpolation and merging to `docker compose config --format json`.
Repeat `-f`, `--env-file` and `--profile` in the intended order; `-p` and
`--project-directory` select the project. Environment, implicit `.env` and Docker
context retain Docker's semantics. Containers are selected by Compose labels.
Missing/stopped services and proven drift block readiness; ambiguous replicas,
custom entrypoints and unavailable evidence remain UNKNOWN. Credentials are
checked for presence, conflicts and readable mounted files, without printing them.

Doctor checks work/temp filesystems inside the server namespace under its observed
UID/GID and supplementary groups. Work requires persistence; temp may use the
container layer. It creates and removes one exclusive small probe per existing
directory, with a container-side timeout. `--no-write-probe` suppresses all doctor
writes and leaves write readiness UNKNOWN. Cleanup failure blocks readiness.
The default reserve is 1 GiB and 1024 inodes per filesystem, configurable with
`--min-free-bytes` and `--min-free-inodes`. Shared work/temp filesystems are counted
once. This policy does not guarantee capacity for future Telegram traffic.
Thresholds must be positive integers. Mount metadata is checked for enabled
quotas; without per-identity quota accounting that evidence remains UNKNOWN.
The exclusive write uses an open descriptor in the verified directory, and
cleanup removes only that probe after checking its identity.
Probe UID, GID and supplementary groups must match the observed server identity;
a successful root write cannot satisfy this check. Existing canonical directories
are required; doctor does not create roots, change ownership or change modes.

Doctor blocks any override which aliases the private state root or mounts its
backing into an HTTP component, including read-only mounts. The shipped nginx
configuration proxies requests and its logging redaction map is supported.
Doctor does not repair nginx or Compose.
Isolation checks parse supported nginx blocks/includes and compare mount backings.
Dynamic handlers, unresolved includes and unverified media symlinks remain UNKNOWN.
No binlog, real bot directory, statistics endpoint or state file is fetched.
Read-only mounts, disabled directory listings and loopback publication do not
prevent known-file HTTP reads. Unsupported remote file workflows use the boundary
in issue #5; doctor does not certify or execute neighboring migration helpers.
## Helper access

The operator startup file allowlists full API endpoints. The loopback helper
serves fixed routes/assets and accepts no arbitrary Docker command/container.
One-time bootstrap creates an HttpOnly SameSite=Strict cookie and CSRF token.
Exact Host/Origin checks reject external/null/file origins. Limits: 256 KiB body,
ten-second HTTP lifetime, sixteen connections and one background migration.
Access/body logs are disabled. The helper is never exposed through nginx.

## Private migration authority

Use one `MIGRATION_STATE_DIR` per operator/host on a private Linux filesystem
outside the checkout, Bot API mounts and webroots (directory 0700, files 0600).
All interfaces share its per-bot lock and unfinished-operation reservation.
Windows and Windows-mounted WSL state are unsupported. Nested private artifacts
are rejected by the documentation checker.

Readiness is a fresh token-free protocol probe plus private deployment evidence
with a five-minute TTL. Bind the image ID, runtime UID/GID, credentials readiness,
persistent work mount and writable separate temp path. A local-build image need
not have a RepoDigest; temp storage need not be persistent. `_FILE` credentials
are supported. Managed Docker diagnostics perform explicit tiny write probes as
the runtime user; they are not read-only. The HTTP helper cannot select containers.
Local webhook mode must match deployment evidence: HTTP/private IP/any port is
allowed in local mode; cloud requires HTTPS, a supported port and public IPv4.
Unsupported profiles fail before source mutations. Transport has bounded DNS,
connect/read/total time and body size, no redirects, inherited proxy or retries.

## Addresses and storage

| Setting | Value |
| --- | --- |
| Gateway port on the host | `18080` |
| Internal Bot API endpoint | `http://botapi:8081` |
| Persistent state on the host | `./data` |
| Gateway upload spool | Project-scoped `gateway_client_temp` volume at `/var/cache/nginx/client_temp` |
| State directory inside the container | `/var/lib/telegram-bot-api` |
| Container user/group IDs | `101:101` |
| Local mode | Enabled by Compose |

The Bot API endpoint receives method calls. The webhook URL belongs to your
application and receives updates sent by the server. They are different addresses.

## Compose environment

| Variable in `.env` | Purpose |
| --- | --- |
| `API_ID` | Required application API ID |
| `API_HASH` | Required application API hash |
| `GATEWAY_BIND` | Gateway host address; defaults to `127.0.0.1` |
| `BOTAPI_IMAGE` | Optional image tag or digest; defaults to `ghcr.io/ichinya/tg-selfhost-botapi:latest` |

For a tested build, set:

```text
BOTAPI_IMAGE=ghcr.io/ichinya/tg-selfhost-botapi:build-<key>
```

An image digest can be used instead. The local build override uses
`tg-selfhost-botapi:local`, independently of `BOTAPI_IMAGE`.

## Migration helper environment

The host helper imports the documented migration settings from trusted `.env`/`ENV_FILE`, including `OFFICIAL_BOT_URL`. See complete-profile inputs below; these are separate from container settings.

## Container environment

These variables configure the image's entrypoint. Compose currently maps
`API_ID/API_HASH` into `TELEGRAM_API_ID/TELEGRAM_API_HASH`.

| Variable | Purpose / default |
| --- | --- |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | Required credentials |
| `TELEGRAM_API_ID_FILE`, `TELEGRAM_API_HASH_FILE` | Read the corresponding credential from a mounted file |
| `TELEGRAM_WORK_DIR` | State directory; set by the image |
| `TELEGRAM_TEMP_DIR` | Temporary directory; set by the image |
| `TELEGRAM_HTTP_PORT` | Bot API port; `8081` |
| `TELEGRAM_LOCAL` | Local mode; Compose sets `true` |
| `TELEGRAM_STAT` | Statistics endpoint on port `8082`; disabled by default |
| `TELEGRAM_LOG_FILE`, `TELEGRAM_VERBOSITY` | Log destination and verbosity |
| `TELEGRAM_FILTER` | Bot user-ID filter |
| `TELEGRAM_MAX_CONNECTIONS`, `TELEGRAM_MAX_WEBHOOK_CONNECTIONS` | Connection limits |
| `TELEGRAM_PROXY` | Outgoing webhook HTTP proxy |
| `TELEGRAM_HTTP_IP_ADDRESS` | Bot API listen address |

Boolean flags accept `true/false` or `1/0`. Do not set both a credential and its
`_FILE` variant. File-based credentials require mounting the files and changing
the service's environment mapping; simply adding `_FILE` to `.env` is insufficient.

Keep the statistics endpoint internal: upstream output may contain bot tokens.
The gateway currently forwards to port `8081`; changing the container's port also
requires updating nginx.

## Webhook User-Agent

The build applies `patches/webhook-user-agent.patch` to the official server.
Outgoing updates include `User-Agent: WebhookDelivery/1.0`. The neutral name avoids
recipient-side crawler filters that reject User-Agents containing `bot`. Incoming nginx
headers or a header on `setWebhook` do not configure this outgoing header.

## Files in local mode

`getFile` can return an absolute container-local path. A bot application needs a
matching shared volume/path to read that file directly. Do not turn an arbitrary
absolute path into an HTTP download URL.

The previously documented `X-Telegram-Bot-Token` download scheme is not implemented.
A remote authenticated file handler is tracked in
[issue #5](https://github.com/ichinya/tg-selfhost-botapi/issues/5).

## Current limitations

- nginx forwards `/file/` requests to the Bot API; it does not serve the state directory.
- nginx limits the entire request body to `2048m` (2,147,483,648 bytes), including
  multipart fields and all attachments; larger requests receive HTTP 413. Request
  buffering is on and uses the separate disk-backed spool before forwarding.
  Client body and upstream send idle timeouts are 300 seconds, upstream read is
  600 seconds, and upstream connect is 5 seconds. These are not total deadlines.
- The gateway binds to localhost by default. Set `GATEWAY_BIND=0.0.0.0` in `.env`
  only if remote clients, such as a webhook receiver, must reach it; protect external
  access with HTTPS and appropriate network controls.
- Access logs redact bot tokens and omit query strings. nginx error logs use the
  `crit` threshold to suppress request-bearing errors; warning and error diagnostics
  are not logged. Critical messages can still contain secrets: filter logs before
  exporting them and do not share unredacted diagnostics.

[Getting started](getting-started.md) · [Maintenance](maintenance.md)

## Complete webhook profile inputs

Before source mutations, the helper resolves `WEBHOOK_SECRET_MODE=provided|none`, `WEBHOOK_IP_MODE=dns|pinned`, `WEBHOOK_CERTIFICATE_MODE=provided|none`, `WEBHOOK_ALLOWED_UPDATES` (JSON array of strings), `WEBHOOK_MAX_CONNECTIONS` and `WEBHOOK_TARGET_LOCAL=true|false`. Unknown secret/IP and unavailable custom certificates stop preflight. `fixed` is an alias for pinned canonical IPv4. Source `ip_address` does not reveal pinning intent. Explicit inputs override source; omitted optional updates become the documented `[]` default. `[]` excludes chat_member, message_reaction and message_reaction_count; it is not every update type. Null or invalid values fail. Per-bot max_connections is 1–100; up to 100000 requires explicit local-mode capability (`TELEGRAM_LOCAL`/`--local`), independently of server `TELEGRAM_MAX_WEBHOOK_CONNECTIONS`. A self-host URL does not establish this capability.

Use `WEBHOOK_SECRET_TOKEN` or `WEBHOOK_SECRET_TOKEN_FILE`, exactly one for provided mode; none asserts an intentionally unprotected webhook. Secret files allow one final LF/CRLF; inline secrets are never trimmed. Use `WEBHOOK_CERTIFICATE_FILE` for a public PEM, never a private key. Protected files (including `BOT_TOKEN_FILE`) must be outside checkout/webroot, with operator-only access. Values from the process override trusted `ENV_FILE` (default: helper directory `.env`), including explicitly empty values; value/file pairs are selected at one tier. Positional URLs remain highest priority. Polling has no webhook profile.

Full profile transport is enabled: urlencoded without a certificate, entirely multipart with a certificate. Secret/scalar files are private snapshots; no token/secret/URL is placed in curl argv or raw diagnostics. The helper disables tracing, uses curl -q without redirects, guards HTTP/ok/result and never retries a mutation. Public PEM requires Bash 4+, jq, curl, realpath and openssl X.509 validation; no private key is accepted. Temporary files use umask 077 and are removed on exit/signals.

## Host-side migration timeouts

The root `migrate_off_to_self.sh` helper accepts `MIGRATION_CONNECT_TIMEOUT`
(default 5 seconds, integer 1..60) and `MIGRATION_REQUEST_DEADLINE` (default
30 seconds, integer 1..300). The connect timeout must not exceed the deadline.
The deadline applies to each request; the token-free probe is capped at 10
seconds. Process settings take precedence over the trusted environment file;
only an unset setting uses its default. Unlike the endpoint settings, an
explicitly empty timeout is invalid. These settings are not passed to containers.
