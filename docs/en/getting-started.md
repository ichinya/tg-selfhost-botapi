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
