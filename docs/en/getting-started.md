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

On a Linux VPS record Docker Engine and Compose v2 versions (`docker version`, `docker compose version`), architecture (`uname -m`), available resources and free port 18080. Ensure the daemon, curl and jq are available. CI publishes linux/amd64; ARM support is not established. Use isolated state and a separate daemon or host without conflicting fixed container names or port. Restrict gateway access before starting. `API_ID` and `API_HASH` must be present in `.env` or the environment for config and up: synthetic values suffice for config validation, but actual application credentials are needed to start.

Use an isolated VPS or disposable daemon with an initially empty `./data`, never production volumes: old state can restore bot sessions. The fixed names `tg_botapi` and `tg_gateway` and port 18080 are not isolated by a different Compose project name. The shipped mapping exposes all interfaces and `/file/` serves state: restrict ingress before starting. Keep the same working directory, project, `--env-file .env`, user, context and `DOCKER_CONFIG` throughout; the commands below assume the default `.env` in this directory. Use only the tracked base and build files. Check `docker compose config --help`, `docker compose up --help`, and `docker run --help` for `--quiet`, `--images`, `--no-build`, `--pull`, and the `never` policy. If unavailable, stop and use a compatible CLI; do not omit these flags.

Choose one mode and keep the same Compose files throughout. For a published candidate, replace the placeholder with a verified existing `build-<key>` tag or `ghcr.io/ichinya/tg-selfhost-botapi@sha256:<verified-digest>`; the placeholder is not a usable digest. Export it for both Compose and shell: Compose reads `.env`, but shell commands do not import it.

```sh
export BOTAPI_IMAGE='ghcr.io/ichinya/tg-selfhost-botapi:build-<verified-key>'
export IMAGE="$BOTAPI_IMAGE"
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.yml config --images
docker compose -f docker-compose.yml pull botapi gateway
```

Record the Bot API RepoDigest using the inspect command below, then repeat the published pull with `BOTAPI_IMAGE` set to the actual `ghcr.io/ichinya/tg-selfhost-botapi@sha256:<verified-digest>` and update `IMAGE` to match. The placeholder is not a digest. A failed pull or unavailable digest means exact repeat is not verified.

The gateway pull uses Docker Hub and the access conditions above. For local build instead:

```sh
export IMAGE=tg-selfhost-botapi:local
docker compose -f docker-compose.yml -f docker-compose.build.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.build.yml config --images
docker compose -f docker-compose.yml -f docker-compose.build.yml pull gateway
docker pull alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f
docker compose -f docker-compose.yml -f docker-compose.build.yml build botapi
```

Local build pulls Alpine from Docker Hub and depends on GitHub and APK repositories. Record Dockerfile inputs and build-arg overrides. The default `BUILD_JOBS=1` TDLib build can take tens of minutes or more on a small VPS; reserve RAM and disk and keep the session alive with screen/tmux or SSH. After pull/build, record the chosen reference, ID, OS/architecture, RepoDigests and labels `io.tg-selfhost.bot-api-revision`, `io.tg-selfhost.build-key`, `org.opencontainers.image.source`; local RepoDigests can be empty. Record nginx digest and ID as well. Image config ID is not a manifest digest; labels are not an attestation. The default `nginx:alpine` and `latest` float. Inspect only these fields when sharing results.

```sh
docker image inspect --format 'ID={''{.Id}} OS/arch={''{.Os}}/{''{.Architecture}} digests={''{json .RepoDigests}} source={''{index .Config.Labels "org.opencontainers.image.source"}} revision={''{index .Config.Labels "io.tg-selfhost.bot-api-revision"}} build-key={''{index .Config.Labels "io.tg-selfhost.build-key"}}' "$IMAGE"
docker image inspect --format 'ID={''{.Id}} OS/arch={''{.Os}}/{''{.Architecture}} digests={''{json .RepoDigests}}' nginx:alpine
IMAGE_ID=$(docker image inspect --format '{''{.Id}}' "$IMAGE")
docker run --rm --network none --pull never "$IMAGE_ID" --version
```
Expect version output and exit code 0; no working data or credentials are mounted. Entrypoint passthrough bypasses credentials and ownership setup and does not prove readiness. For an exact gateway repeat, on a disposable daemon only, pull the recorded `nginx@sha256:<verified-digest>`, tag that image locally as `nginx:alpine`, and verify its ID matches the recorded ID. Retagging affects all users of that name; an unavailable digest means repeat is unverified. Start the selected mode:

```sh
# Published:
docker compose -f docker-compose.yml up -d --no-build --pull never
# Local build, instead:
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --no-build --pull never
```

Check both services and compare container Image IDs with the recorded image IDs, including nginx. Both must be running and RestartCount must not increase between two observations; a mismatch or restart loop fails this stage even if HTTP works:

```sh
docker compose -f docker-compose.yml ps
docker inspect --format 'name={''{.Name}} image={''{.Image}} status={''{.State.Status}} restarts={''{.RestartCount}}' tg_botapi tg_gateway
```

For local mode use both `-f` files with `ps`. Do not share full inspect output containing environment.
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
