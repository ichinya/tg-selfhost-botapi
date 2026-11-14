---
title: Getting started
translation: /docs/ru/getting-started.html
---

# Getting started

## File downloads

File downloads require the explicit split-storage override and a scoped reader:
see [configuration](configuration.md) and the
[runnable examples](https://github.com/ichinya/tg-selfhost-botapi/blob/main/examples/files/README.md).
Do not append an absolute getFile path to an HTTP URL. Missing bot directories
must fail closed; never fix a missing mount by exposing the whole private cache.

For deployment, set the qualified image refs from the release receipt in `.env`
before running these commands, including `GATEWAY_IMAGE`. For file-enabled
installations, keep the same ordered files on every command:

```sh
# Prepare BOTAPI_STATE_SOURCE, BOTAPI_TEMP_SOURCE and BOTAPI_MEDIA_SOURCE
# for BOTAPI_UID:BOTAPI_GID as described below, then configure them in .env.
docker compose -f docker-compose.yml -f docker-compose.nonroot.yml -f docker-compose.files.yml up -d
# Local reader, after setting the private bindings described in the example:
docker compose -f docker-compose.yml -f docker-compose.nonroot.yml -f docker-compose.files.yml \
  -f examples/files/compose.local.yml run --rm reader '<FILE_ID>' > downloaded.bin
# Remote per-bot handler (qualified DOWNLOADS_IMAGE and protected files required):
docker compose -f docker-compose.yml -f docker-compose.nonroot.yml -f docker-compose.files.yml \
  -f docker-compose.downloads.yml up -d
```

For a local Bot API build insert `-f docker-compose.build.yml` immediately after
the base file and use `up -d --build`. To build downloads from the saved inputs,
add `-f docker-compose.downloads.build.yml` after `docker-compose.downloads.yml`
and run `docker compose --env-file .env.build -f docker-compose.yml -f docker-compose.files.yml -f docker-compose.downloads.yml -f docker-compose.downloads.build.yml build downloads`; set
`DOWNLOADS_IMAGE` only to a candidate qualified by the file gate. API port is
18080; downloads HTTP port is loopback 18082 behind the supplied TLS frontend.

## Local migration UI

Use Linux/WSL, Python 3.11+ and a private Linux state directory. Create a
mode-0600 helper JSON file outside the checkout:

```json
{"state_dir":"/home/operator/.local/state/tg-selfhost-botapi/migrations","allowed_endpoints":["https://api.telegram.org","http://bot-api.internal:8081"],"evidence_file":"/home/operator/private/deployment.json","trust_file":"/home/operator/private/providers.json","fixture":false}
```

Supply fresh deployment evidence and independent trusted provider keys.
Without them real external checkpoints stay blocked. Start explicitly:

```sh
python3 tools/migration_helper.py --config "$HELPER_CONFIG" --bootstrap-file "$PAIRING_FILE" --port 8765
```

Select a new `PAIRING_FILE` in an operator-owned mode-0700 directory outside the
checkout, journal and Bot API mounts. The helper creates it with mode 0600 and
refuses to overwrite existing files. Read the code privately from that file and
enter it at `http://127.0.0.1:8765/`; it is never printed in startup logs.
Pairing expires after five minutes; authenticated sessions expire after one hour.
Restart the helper with a fresh pairing file to establish a new session.
UI/API share this origin. Pages only explains this workflow. For a remote host:
`ssh -N -L 8765:127.0.0.1:8765 operator@HOST`, then the exact same local URL.

## Requirements

- Docker with Compose v2.
- For doctor: host Python 3.11+ (stdlib only). Full runtime evidence requires a
  local Linux engine with bridge access; pure checks also work on Windows.
- A Telegram application API ID and hash from [my.telegram.org](https://my.telegram.org).
- For migration: Linux/WSL, Python 3.11+; the Bash compatibility adapter also
  needs curl, jq and GNU coreutils on a POSIX host (`mktemp`, `date`, `stat`,
  `mkdir`, `mv`, `chmod`, `rm`, `rmdir`, `cat`) for the retained standalone
  helper path. Private diagnostics require owner-only POSIX permissions; Windows
  runtime validation is deferred to Linux CI.
- Node 24 is required for development/UI acceptance, not for operating the helper.

The application API ID/hash identify your Telegram application. They are different
from a bot token issued by BotFather.

## Prepare

```sh
git clone https://github.com/ichinya/tg-selfhost-botapi.git
cd tg-selfhost-botapi
cp .env.example .env
install -d -m 0700 .observability
install -d -m 0755 .observability/runtime .observability/migration
sudo install -d -o 101 -g 101 -m 0700 .observability/registry .observability/credentials
```

Fill in `API_ID` and `API_HASH` in `.env`. Keep that file private.
Compose validates structure; the entrypoint rejects unset or empty credentials
before starting the server. File secrets are checked as the server user; apply
`docker-compose.secrets.yml` last, including after any local build overlay.

The gateway binds to `127.0.0.1` by default and does not expose the state directory.

Before large uploads, provision disk space and inodes for the gateway's separate
`gateway_client_temp` volume and Bot API storage. The nginx worker needs write
access to the spool. See [configuration](configuration.md) for sizing.
If remote clients, including a webhook receiver, must reach the Bot API, set
`GATEWAY_BIND=0.0.0.0` in `.env` and provide HTTPS and network access controls.

## Start

For a custom non-root identity, create dedicated empty bind directories outside
the webroot and configure the optional override in `.env`:

```sh
sudo install -d -m 0700 -o 1000 -g 1000 /srv/botapi/data /srv/botapi/scratch
```

Set `BOTAPI_UID=1000`, `BOTAPI_GID=1000`,
`BOTAPI_STATE_SOURCE=/srv/botapi/data` and `BOTAPI_TEMP_SOURCE=/srv/botapi/scratch`.

```sh
docker compose -f docker-compose.yml -f docker-compose.nonroot.yml up -d
```

For a local build append `-f docker-compose.build.yml` after the non-root
override and add `--build`. Both bind sources must already exist. Named volumes
require a separate Compose configuration. Initialize each fresh empty volume
once with a root helper, replacing the example volume and IDs:

```sh
docker run --rm --user 0:0 -v botapi-state:/volume alpine:3.22 sh -c 'chown 1000:1000 /volume && chmod 700 /volume'
```

Repeat for a distinct temp volume. Do not apply this to existing data; image
layer ownership does not prepare mounts.

For limited media sharing, use a writer with primary group `2000`: prepare
private state and scratch for `1000:2000`, and a separate media root owned by
`1000:2000` with mode `0700`. Set `BOTAPI_UID=1000`, `BOTAPI_GID=2000`,
`BOTAPI_MEDIA_SOURCE` to that absolute root, and append
`-f docker-compose.files.yml` after the non-root overlay. The gateway receives no
storage mount. Only share one final bot media subtree, never the bot root, its
download temp, private state or neighbouring bots. Set `BOT_MEDIA_SUBDIR` privately
to the host path of the selected bot subtree; its name may contain sensitive data.
For an offline prepared `documents` subtree, directories must permit group search
and read (at most `0750`) and files group read (at most `0640`); existing files
need separate preparation with writers stopped. A synthetic reader test is:

```sh
docker run --rm --user 2001:3000 --group-add 2000 \
  --mount "type=bind,src=$BOT_MEDIA_SUBDIR/documents,dst=/media,readonly" \
  alpine:3.22 cat /media/synthetic.txt
```

Place a synthetic test file there first with the writer identity and group-read
permissions. Do not print the private path in public logs. Download temporary
files reside within the media backing, not `TELEGRAM_TEMP_DIR`; the writer's
primary group survives a same-filesystem rename. The reader gets no Docker socket
or mount privileges. This test does not prove an actual Telegram download.

Before the first GHCR publication, build locally:

```sh
RUNNER_TEMP="${RUNNER_TEMP:-$(mktemp -d)}"
python3 tools/image_inputs.py --capture-wrapper "$RUNNER_TEMP/source-inputs.json"
python3 tools/image_inputs.py --inputs-file "$RUNNER_TEMP/source-inputs.json" --build-env .env.build
docker compose --env-file .env --env-file .env.build -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

Once a published image is available:

```sh
docker compose --env-file .env --env-file selected.env pull
docker compose --env-file .env --env-file selected.env up -d --no-build
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
set -euo pipefail
export BOT_TOKEN_FILE=/secure/bot-token
export SELF_BOT_URL=http://127.0.0.1:18080
python3 - <<'PY'
import json, os, re, sys, urllib.request
sys.path.insert(0, 'tools')
from migration_cli import private_text
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args): return None
try:
    token = re.sub(r'\r?\n$', '', private_text(os.environ['BOT_TOKEN_FILE']))
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token): raise ValueError()
    client = urllib.request.build_opener(NoRedirect)
    for method in ['getMe']:
        url = os.environ['SELF_BOT_URL'].rstrip('/') + '/bot' + token + '/' + method
        data = b'drop_pending_updates=false' if method == 'deleteWebhook' else None
        with client.open(urllib.request.Request(url, data=data), timeout=15) as response:
            result = json.load(response)
        if result.get('ok') is not True: raise ValueError()
        if method == 'deleteWebhook' and result.get('result') is not True: raise ValueError()
        if method == 'getWebhookInfo' and result['result']['url'] != '': raise ValueError()
    print('api_checks_pass; delivery_not_verified')
except Exception:
    raise SystemExit('request_failed; reconcile before retry') from None
PY
```

These examples use Bash and Python with private-file input. The token stays in
the HTTP client process; only a fixed result is printed. Use the qualified gateway
and native image logging policy described in configuration.

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
Optional file credentials: follow the [Compose secrets profile](configuration.md#docker-compose-file-secrets), store files outside checkout, and apply secrets after the build overlay.


The standalone exported plan requires Bash 4+ on Linux/WSL; run the saved file with `bash ./migration-plan.sh`. It is not a PowerShell or cmd script.

## Token-free health

The management listener provides exact GET/HEAD `/health/live` and `/health/ready`
from cached root probes. A valid Bot API JSON 404 is expected; HTML, redirects,
timeouts and stale success fail closed. Stats off means `http_handler_only`;
stats on adds a recognized manager response (`http_handler_and_manager`).
Neither depth authenticates a bot or confirms Telegram connectivity/delivery.
`/status` is a document, not an overall UP signal. Internal `/selfz` only checks
the observer scheduler and is not available through the management gateway.

Registry startup requires a qualified complete `selected.env` and its archived receipt;
`selected_release: null` means no release is accepted. These startup examples are not an update procedure;
use the [maintenance runbook](maintenance.md#cold-backup-update-and-data-aware-rollback) for an existing installation.
