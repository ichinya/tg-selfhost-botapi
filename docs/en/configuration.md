---
title: Configuration
translation: /docs/ru/configuration.html
---

# Configuration

## Addresses and storage

| Setting | Value |
| --- | --- |
| Gateway port on the host | `18080` |
| Internal Bot API endpoint | `http://botapi:8081` |
| Persistent state on the host | `./data` |
| State directory inside the container | `/var/lib/telegram-bot-api` |
| Media on the host / in the container | `./files` / `/var/lib/telegram-bot-api-files` |
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

The Bash migration helper reads only `SELF_BOT_URL`, `TELEGRAM_BOT_URL`, `WEBHOOK_URL`, `WEB_HOOK` and `DROP_PENDING_UPDATES` from its trusted `.env` file; other values there are not exported to the helper. `OFFICIAL_BOT_URL` is an advanced testing override for the source endpoint and is read from the process environment, not from that file.

## Container environment

These variables configure the image's entrypoint. Compose currently maps
`API_ID/API_HASH` into `TELEGRAM_API_ID/TELEGRAM_API_HASH`.

| Variable | Purpose / default |
| --- | --- |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | Required credentials |
| `TELEGRAM_API_ID_FILE`, `TELEGRAM_API_HASH_FILE` | Read the corresponding credential from a mounted file |
| `TELEGRAM_WORK_DIR` | State directory; set by the image |
| `TELEGRAM_TEMP_DIR` | Temporary directory; set by the image |
| `TELEGRAM_FILES_DIR` | Separate media root / `--files-dir`; set by Compose, unset preserves the upstream legacy default |
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

Compose separates private state (`./data`) from media (`./files`). In split mode
the entrypoint rejects noncanonical, symlinked or overlapping roots; temp and logs
must stay outside media. Relative `TELEGRAM_LOG_FILE` resolves inside the work
directory. Explicit CLI arguments bypass environment/profile validation, including
credential-free `--help` and `--version`.

Writer UID/GID is `101:101`, media root must be mode `770`, writer umask is `007`.
Prepare only the selected bot directory as `101:101`, mode `2750`; reader
`10001:101` needs group read/traverse (or a targeted operator ACL). No recursive
ownership or permission changes are applied to existing state. An existing media
root with incompatible owner/mode fails startup; prepare that root privately.
Actual TDLib-created file permissions must pass the qualified-image runtime gate;
the umask and shell writer fixture alone do not prove them.

`getFile` can return an absolute container-local path. A bot application needs a
matching shared volume/path to read that file directly. Do not turn an arbitrary
absolute path into an HTTP download URL.

The local reader accepts one `file_id`, resolves it through the operator's private
Bot API endpoint and reads the returned absolute path unchanged. Its read-only
mount must contain only that bot's full-token/DC directory, at the identical
container path. A numeric bot ID alone is insufficient; test DC appends `:T`,
and the alternative layout replaces `:` with `~`. Telegram token comes from a
separate protected regular secret file (owner root/reader, mode `0640` or stricter,
no symlink/hardlink), never from a command argument.

The shared opener requires Linux/amd64, kernel >= 5.6 and working openat2 under
seccomp. It pins the root and opens a single regular, single-link FD below it;
symlinks, nested mounts, traversal and outside paths fail closed, with no pathname
fallback. Direct local access is isolated by mounts and Unix permissions. Writer
and operator are trusted; an FD is not a snapshot of mutable writer data.

The previously documented `X-Telegram-Bot-Token` scheme is not implemented.

After preparing private paths and a qualified image pair as described in
`examples/files/README.md`, run the local reader with a nonsecret test file ID:

```sh
docker compose -f docker-compose.yml -f examples/files/compose.local.yml run --rm reader '<FILE_ID>' > downloaded.bin
```

### Remote download contract (opt-in)

The base gateway has no HTTP file-download service. The separate opt-in handler
accepts `POST /downloads/<bot-alias>`, exactly `Content-Type: application/json`,
one `Authorization: Bearer <DOWNLOAD_CREDENTIAL>` and only
`{"file_id":"<FILE_ID>"}`. Registry maps each alias to a unique credential of at
least 32 random characters, full Telegram token/DC, private endpoint and bot-root.
Clients cannot set paths, token, endpoint or root. Duplicate/extra keys, query
strings, duplicate auth/framing, chunked request bodies and legacy auth fail.

Missing/wrong/revoked/duplicate credential returns 401. A valid credential for a
different or unknown alias returns the same 403, before getFile/open. Invalid
input or Content-Type returns 400, unsupported methods 405, Range 416, size limits
413, unavailable/forbidden file 404, upstream failure/timeout 502/504, overload
503. Success is octet-stream with a fixed attachment name, FD Content-Length,
no-store and nosniff. No private paths or raw upstream diagnostics are returned.

Bounds: 4 workers plus 8 queued connections; headers/body <= 16 KiB; file_id <=
1024 UTF-8 bytes; upstream connect/read deadlines 5/60 seconds; client idle 30
seconds; chunks 64 KiB. No HEAD, Range, resume or transparent retries. A stream
error closes the connection without adding JSON. Rotate the private registry
credential and recreate the handler to revoke it. Protect remote transport with
HTTPS; Telegram tokens stay on the server. Untrusted clients must not have direct
access to local Bot API methods; this handler is not a tenant isolation layer for
the entire Bot API.

Start the opt-in profile after privately configuring `.env` and the registry:

```sh
docker compose -f docker-compose.yml -f docker-compose.downloads.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.downloads.yml up -d downloads downloads-gateway
curl --config /absolute/private/download.curl --fail-with-body \
  --header 'Content-Type: application/json' --data '{"file_id":"<FILE_ID>"}' \
  https://downloads.example.com/downloads/bot-a --output downloaded.bin
```

The private curl file contains the Bearer header. Backend has no host port; the
separate proxy binds `127.0.0.1:18082`, with disk buffering/cache disabled. Use
`examples/files/nginx.downloads-tls.conf` at the operator's HTTPS ingress. Each
registered bot needs its own read-only bind; missing source paths fail startup.
Registry and token must be outside media. Never publish resolved token/DC paths.

## Current limitations

- nginx forwards `/file/` requests to the Bot API; it does not serve the state directory.
- No upload-size override is configured in nginx. Large multipart requests can
  receive HTTP 413; [issue #4](https://github.com/ichinya/tg-selfhost-botapi/issues/4).
- The gateway binds to localhost by default. Set `GATEWAY_BIND=0.0.0.0` in `.env`
  only if remote clients, such as a webhook receiver, must reach it; protect external
  access with HTTPS and appropriate network controls.
- Access logs redact bot tokens and omit query strings. nginx error logs use the
  `crit` threshold to suppress request-bearing errors; warning and error diagnostics
  are not logged. Critical messages can still contain secrets: filter logs before
  exporting them and do not share unredacted diagnostics.

[Getting started](getting-started.md) · [Maintenance](maintenance.md)
