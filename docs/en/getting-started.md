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

## Registry access

| Registry | Use |
| --- | --- |
| GHCR | Published Bot API image |
| Docker Hub | `nginx:alpine` gateway and pinned `alpine` base image for local builds |

Public images can be pulled anonymously while access and applicable limits permit it. Private images require an authorized account; login may help with an anonymous pull limit, but does not fix every 429. See [Docker Hub pull limits](https://docs.docker.com/docker-hub/usage/pulls/). Hub login does not authenticate GHCR.

Set `DOCKERHUB_USER` to your username and `DOCKERHUB_TOKEN_FILE` to a PAT file outside the repository, readable only by its owner. Provision it privately without putting the token in shell history. Disable tracing and do not print the file or token:

```sh
set +x
docker login --username "$DOCKERHUB_USER" --password-stdin < "$DOCKERHUB_TOKEN_FILE"
```

Expect exit code 0 and `Login Succeeded`; then separately pull the required reference and expect exit 0; login alone does not prove image access. Alternatively, run `docker login --username "$DOCKERHUB_USER"` and enter the PAT at the hidden prompt. Without `--username`, Docker Hub uses device-code login. A private GHCR package needs separate credentials with package-read access: `docker login ghcr.io --username "$GHCR_USER" --password-stdin < "$GHCR_TOKEN_FILE"`. Protect that file in the same way.

Use the same Unix user, Docker context and `DOCKER_CONFIG` for login and pull; `sudo docker` can use a different configuration. Use a credential helper: without one Docker may store credentials base64-encoded, not encrypted, in `config.json`. Do not put registry PATs in Compose environment or application `.env`, or include Docker config in reports.

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
