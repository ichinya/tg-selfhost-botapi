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

These are host-side helper settings, not container environment. This is the exact trusted-file whitelist; all other keys are ignored. `OFFICIAL_BOT_URL` is process-only for isolated tests. Presence-aware precedence and empty input semantics: [migration](migration.md).

| Variable | Meaning |
| --- | --- |
| `SELF_BOT_URL`, `TELEGRAM_BOT_URL` | Target Bot API; legacy alias |
| `WEBHOOK_URL`, `WEB_HOOK` | Receiver URL; ignored by polling/preserve |
| `WEBHOOK_ACTION` | Required: preserve / set / polling; no default |
| `DROP_PENDING_UPDATES` | true / false; default false; target mutation only |
| `WEBHOOK_TARGET_LOCAL` | true / false; default false; operator assertion of --local |
| `WEBHOOK_SECRET_MODE` | `provided` / `none`; explicit selection required for webhook |
| `WEBHOOK_SECRET_TOKEN`, `WEBHOOK_SECRET_TOKEN_FILE` | Private secret value OR readable file; API alphabet, 1-256 chars |
| `WEBHOOK_ALLOWED_UPDATES` | JSON array of strings; default []; empty string is invalid |
| `WEBHOOK_MAX_CONNECTIONS` | Integer; default 40; cloud 1-100, confirmed local up to 100000 and server limit |
| `WEBHOOK_IP_MODE`, `WEBHOOK_IP_ADDRESS` | `dns` / `fixed`; fixed requires explicit IP; observed IP is not provenance |
| `WEBHOOK_CERTIFICATE_MODE`, `WEBHOOK_CERTIFICATE_FILE` | `provided` / `none`; Readable nonempty public PEM for provided; private keys rejected; openssl required |

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
