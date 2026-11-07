---
title: Getting started
translation: /docs/ru/getting-started.html
---

# Getting started

## Local migration UI

Use Linux/WSL, Python 3.11+ and a private Linux state directory. Create a
mode-0600 helper JSON file outside the checkout:

```json
{"state_dir":"/home/operator/.local/state/tg-selfhost-botapi/migrations","allowed_endpoints":["https://api.telegram.org","http://bot-api.internal:8081"],"evidence_file":"/home/operator/private/deployment.json","trust_file":"/home/operator/private/providers.json","fixture":false}
```

Supply fresh deployment evidence and independent trusted provider keys.
Without them real external checkpoints stay blocked. Start explicitly:

```sh
python3 tools/migration_helper.py --config "$HELPER_CONFIG" --port 8765
```

Open `http://127.0.0.1:8765/` and enter the one-time code printed in the terminal.
UI/API share this origin. Pages only explains this workflow. For a remote host:
`ssh -N -L 8765:127.0.0.1:8765 operator@HOST`, then the exact same local URL.

## Requirements

- Docker with Compose v2.
- For doctor: host Python 3.11+ (stdlib only). Full runtime evidence requires a
  local Linux engine with bridge access; pure checks also work on Windows.
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
