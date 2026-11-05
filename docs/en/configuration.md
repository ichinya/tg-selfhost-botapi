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
| Server identity | Root bootstrap drops to `101:101`; Docker `user` selects a direct non-root identity |
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

- The nginx `/file/` alias exposes the state directory; it is not an authenticated
  file-download API. Restrict access; [issue #3](https://github.com/ichinya/tg-selfhost-botapi/issues/3).
- No upload-size override is configured in nginx. Large multipart requests can
  receive HTTP 413; [issue #4](https://github.com/ichinya/tg-selfhost-botapi/issues/4).
- Compose publishing `18080:80` does not limit access to localhost.
- Access logs and token-bearing URLs need care; do not share unredacted diagnostics.

[Getting started](getting-started.md) · [Maintenance](maintenance.md)

## Runtime identity

By default the entrypoint starts as root, changes ownership of the state and
temporary directory roots to `101:101`, and starts the server as that account.
It does not recursively repair existing files. With Docker `user` set to a
non-root identity, the entrypoint keeps that identity and its supplementary
groups, does not change ownership, and requires both directories to be writable
and searchable. Numeric users need no passwd entry; a named Docker user follows
the same non-root path. New directories created by the entrypoint use mode
`0750` under umask `0027` and belong to the creating identity. Mounted `_FILE`
secrets must be readable and the parent of `TELEGRAM_LOG_FILE` writable and
searchable by the effective server identity. Explicit command arguments bypass
service defaults and volume preparation.

New files belong to the effective server UID; their group comes from its primary
GID or an existing setgid directory. Umask `0027` limits ordinary `0666` file
creation to `0640`; explicit upstream `0600` remains private. It does not make old
data readable. When replacing the state bind with a named volume, initialize a
new dedicated volume offline with the chosen owner/mode before direct non-root
startup. The default root bootstrap only changes the two top directories; it
does not migrate nested old files. Verify create/read/rename under the writer's
actual identity; adapt existing volumes through the [offline runbook](maintenance.md#changing-storage-identity).

The optional `docker-compose.nonroot.yml` sets Docker user from `BOTAPI_UID` and
`BOTAPI_GID` and mounts the pre-created `BOTAPI_TEMP_SOURCE` directory. See
[Getting started](getting-started.md#optional-non-root-compose).

Ports 8081 and 8082 are unprivileged; a custom UID needs no extra capabilities
to bind them. File-sourced Compose secrets retain host-source permissions:
prepare them for the effective UID, because YAML `uid`, `gid` and `mode` do not
change those host permissions.

## Shared media reader

The runnable synthetic example below uses writer `1000:2000` and reader
`3000:3000` with supplementary group `2000`. Store `ISSUE21_MEDIA_PATH` in private
configuration: it is an administrator-approved absolute media leaf for one bot,
mounted at the same absolute path returned by trusted `getFile.file_path`. A path
may contain a bot token; do not print it in diagnostics. Never mount the bot root,
state root or temp into the reader, and never accept an arbitrary client path.

Prepare only the approved leaf as `0750` and its shared files as `0640`, owned by
writer `1000:2000`; private state/temp roots stay `0700`. Primary writer GID 2000
keeps the group after a create in temp followed by rename. Existing `0600` files
stay private. This is a read-only contract, not group write access. The example's
probe expects synthetic files created by the runtime gate; a production reader
uses its own application command and verified media layout.

```yaml
services:
  botapi:
    user: "1000:2000"
  reader:
    image: ${BOTAPI_IMAGE:?Set BOTAPI_IMAGE}
    user: "3000:3000"
    group_add: ["2000"]
    network_mode: none
    entrypoint: ["/bin/sh", "/reader-probe.sh"]
    environment:
      MEDIA_PATH: ${ISSUE21_MEDIA_PATH:?Set ISSUE21_MEDIA_PATH}
    volumes:
      - type: bind
        source: ${ISSUE21_MEDIA_PATH:?Set ISSUE21_MEDIA_PATH}
        target: ${ISSUE21_MEDIA_PATH:?Set ISSUE21_MEDIA_PATH}
        read_only: true
        bind:
          create_host_path: false
      - type: bind
        source: ./tools/fixtures/issue21/reader-probe.sh
        target: /reader-probe.sh
        read_only: true
        bind:
          create_host_path: false
```

From the repository root, set `BOTAPI_IMAGE` and the private `ISSUE21_MEDIA_PATH`,
then run `docker compose -f docker-compose.yml -f
 tools/fixtures/issue21/docker-compose.reader.yml run --rm --no-deps reader` for the
synthetic probe. The fixture checks both shared-group access and the read-only
mount, with no neighbouring bot/private storage visible. It models filesystem
create/rename, not an actual Telegram download. It does not prepare existing
storage recursively. Shared access excludes private migration state. After #5
introduces a separate media root, apply the same restricted mapping there.
Nginx worker processes may discard supplementary groups; adding a group to the
master does not prove worker access. HTTP file serving remains tracked in #3/#5.
