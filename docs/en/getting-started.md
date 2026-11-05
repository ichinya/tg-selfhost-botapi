---
title: Getting started
translation: /docs/ru/getting-started.html
---

# Getting started

## Requirements

- Docker with Compose v2.
- A Telegram application API ID and hash from [my.telegram.org](https://my.telegram.org).
- For the Bash migration helper: Bash, curl and jq.

The application API ID/hash identify your Telegram application. They are different
from a bot token issued by BotFather.

## Prepare

```sh
git clone https://github.com/ichinya/tg-selfhost-botapi.git
cd tg-selfhost-botapi
cp .env.example .env
```

Fill in `API_ID` and `API_HASH` in `.env`. Keep that file private.

Before starting on a publicly reachable host, restrict gateway access. In
`docker-compose.yml`, replace the published port with:

```yaml
ports:
  - "127.0.0.1:18080:80"
```

The supplied configuration currently binds all host interfaces and serves the
data directory under `/file/`. Use a trusted local environment until the
[file-access issue](https://github.com/ichinya/tg-selfhost-botapi/issues/3)
is resolved. A remote deployment also needs HTTPS and access controls.

## Start

Before the first GHCR publication, build locally:

```sh
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

Once a published image is available:

```sh
docker compose pull
docker compose up -d
```

For a private GHCR package, authenticate with an account that has package access;
for anonymous pulls, the repository owner must make the package public.
Local compilation can take a long time. The default build uses one compilation job.

## Verify

```sh
docker compose ps
docker compose logs --tail=100 botapi gateway
curl --connect-timeout 5 --max-time 10 -i http://127.0.0.1:18080/
```

A response from the Bot API path confirms HTTP reachability, even if it reports a
missing method or token. It does not confirm a bot session or webhook delivery.

The application endpoint is:

```text
http://127.0.0.1:18080/bot<TOKEN>/<METHOD>
```

Use token-bearing calls only on the chosen server at the appropriate migration
stage. To check a bot already assigned to this server:

```sh
read -rsp 'Bot token: ' BOT_TOKEN; printf '\n'
curl --connect-timeout 5 --max-time 15 \
  "http://127.0.0.1:18080/bot$BOT_TOKEN/getMe"
unset BOT_TOKEN
```

These command examples use Bash. A token expanded into curl's URL can be visible
in process arguments and access logs; run diagnostics in a trusted environment.

[Configure the service](configuration.md) · [Move an existing bot](migration.md)
## Optional non-root Compose

Prepare `./data` and a separate disk directory outside the checkout and state
tree, owned by the selected UID:GID, normally mode `0700`. Set `BOTAPI_UID`,
`BOTAPI_GID` and `BOTAPI_TEMP_SOURCE` in your private environment. Apply files in
order: `docker compose -f docker-compose.yml -f docker-compose.build.yml -f
docker-compose.nonroot.yml up -d botapi` (omit the build file for a published
image). The temp source must already exist. A secrets overlay, if used, is applied
last and still requires readable secret files. UID 0 uses the normal root
bootstrap, which drops to 101. API proxying is separate from the legacy `/file/`
alias, whose availability and safety with custom users are not guaranteed; see
issues #3 and #5.

For new empty storage only, a targeted preparation example is
`sudo install -d -m 0700 -o 1000 -g 2000 ./data /srv/tg-selfhost-botapi/temp`.
Inspect both paths first; for existing data use the [offline runbook](maintenance.md#changing-storage-identity).
For a published image, the explicit service command is:

```sh
docker compose -f docker-compose.yml -f docker-compose.nonroot.yml up -d botapi
```

Set all three variables, including a disk temp path, before this command. They
only interpolate the override, not the image's environment API. Readable secrets
and a writable/searchable log parent are required under the same UID/GID.

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
