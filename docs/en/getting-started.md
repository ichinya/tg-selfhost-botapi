---
title: Getting started
translation: /docs/ru/getting-started.html
---

# Getting started

## Requirements

- Docker with Compose v2.
- For doctor: host Python 3.11+ (stdlib only). Full runtime evidence requires a
  local Linux engine with bridge access; pure checks also work on Windows.
- A Telegram application API ID and hash from [my.telegram.org](https://my.telegram.org).
- For the Bash migration helper: Bash, curl, jq and GNU coreutils on a POSIX host
  (`mktemp`, `date`, `stat`, `mkdir`, `mv`, `chmod`, `rm`, `rmdir`, `cat`). Private
  diagnostics require owner-only POSIX permissions; Windows runtime validation is
  deferred to Linux CI. Python and Node are needed only for tests.

The application API ID/hash identify your Telegram application. They are different
from a bot token issued by BotFather.

## Prepare

```sh
git clone https://github.com/ichinya/tg-selfhost-botapi.git
cd tg-selfhost-botapi
cp .env.example .env
```

Fill in `API_ID` and `API_HASH` in `.env`. Keep that file private.

The gateway binds to `127.0.0.1` by default and does not expose the state directory.
If remote clients, including a webhook receiver, must reach the Bot API, set
`GATEWAY_BIND=0.0.0.0` in `.env` and provide HTTPS and network access controls.

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

The release index targets `linux/amd64` and `linux/arm64`. Docker selects the host
variant automatically; Compose does not force a CPU. Local builds also use the
native platform. `--platform` is a diagnostic override and does not prove native
execution. Check the resolved image separately from the host:

{% raw %}
```sh
docker info --format '{{.Architecture}}'
docker compose images -q botapi | xargs docker image inspect --format '{{.Os}}/{{.Architecture}} {{.Id}}'
docker compose exec botapi telegram-bot-api --version
```
{% endraw %}

Release qualification also extracts the actual binary and checks ELF machine ID
62 (amd64) or 183 (arm64). An architecture label alone is insufficient.
Docker Desktop on Apple Silicon needs separate verification. Back up state and
check compatibility before changing CPU architecture; existing TDLib state is
not declared portable by this image pipeline.

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

## Run doctor

After starting the selected installation, run:

```sh
python3 tools/doctor.py -f docker-compose.yml --scenario official-to-self --format json
```

Without private migration decisions the result remains UNKNOWN. The default gateway
only proxies requests and does not serve state. An unsafe operator override that
exposes state through an alias, file server, or gateway mount is BLOCKED. See
[maintenance](maintenance.md) for exits and
scope, [configuration](configuration.md) for Compose/storage inputs, and
[migration](migration.md) for the private input contract. READY is a snapshot of
preconditions; it does not authorize a bot or perform a transfer.
