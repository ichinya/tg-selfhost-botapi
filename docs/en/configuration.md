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
| `BOTAPI_IMAGE` | Optional image tag or digest; defaults to `ghcr.io/ichinya/tg-selfhost-botapi:latest` |

For a tested build, set:

```text
BOTAPI_IMAGE=ghcr.io/ichinya/tg-selfhost-botapi:build-<key>
```

An image digest can be used instead. The local build override uses
`tg-selfhost-botapi:local`, independently of `BOTAPI_IMAGE`.

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
Outgoing updates include `User-Agent: TelegramBotWebhook/1.0`. Incoming nginx
headers or a header on `setWebhook` do not configure this outgoing header.

## Files in local mode

`getFile` can return an absolute container-local path. A bot application needs a
matching shared volume/path to read that file directly. Do not turn an arbitrary
absolute path into an HTTP download URL.

The previously documented `X-Telegram-Bot-Token` download scheme is not implemented.
A remote authenticated file handler is tracked in
[issue #5](https://github.com/ichinya/tg-selfhost-botapi/issues/5).

## Current limitations

- The nginx `/file/` alias exposes the state directory; it is not an authenticated
  file-download API. Restrict access; [issue #3](https://github.com/ichinya/tg-selfhost-botapi/issues/3).
- No upload-size override is configured in nginx. Large multipart requests can
  receive HTTP 413; [issue #4](https://github.com/ichinya/tg-selfhost-botapi/issues/4).
- Compose publishing `18080:80` does not limit access to localhost.
- Access logs and token-bearing URLs need care; do not share unredacted diagnostics.

[Getting started](getting-started.md) · [Maintenance](maintenance.md)
