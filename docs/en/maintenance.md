---
title: Maintenance
translation: /docs/ru/maintenance.html
---

# Maintenance

## Image pipeline

The image workflow checks official tdlib source and the Alpine 3.22 digest every
night around **04:37 Asia/Yekaterinburg** (23:37 UTC), on default-branch changes,
and on manual runs. GitHub may delay scheduled runs.

The build key covers the resolved revisions/digests, recipe, entrypoint, patch,
Compose files, permission runner and all issue-21 acceptance fixtures. If the
corresponding published build exists, compilation is skipped and that candidate
is loaded by registry digest. Its build-key and source-revision labels are
checked, then the same smoke and runtime gates run again. If registry inspection
cannot confirm it, the pipeline rebuilds.

For a new build it:

1. Checks that the User-Agent patch applies to the selected official revision.
2. Compiles the entire server.
3. Runs `--version`, checks the header string in the binary and validates entrypoint syntax.
4. Runs the mandatory Linux permission matrix, including the restricted reader.
5. Publishes `ghcr.io/ichinya/tg-selfhost-botapi:build-<key>`, verifies its digest
   resolves to the tested local image ID and promotes that digest to `latest`.

Failed checks leave the previously published `latest` in place. Pull requests do
not publish. A binary string check is not a live webhook-delivery test.

The workflow needs to be on the default branch before the schedule/publication
can work. GHCR writes use `GITHUB_TOKEN` with `packages: write`. Configure package
visibility or client authentication after the first publication.

## Update an installation

If you started with `docker-compose.nonroot.yml`, include
`-f docker-compose.yml -f docker-compose.nonroot.yml` in every registry update
command below. For a local build, include `-f docker-compose.nonroot.yml` after
the build override in every command.

Registry publication does not restart your VPS. Select a tested tag/digest with
`BOTAPI_IMAGE` in `.env`, then:

```sh
docker compose stop botapi
# Make a consistent backup of ./data and private configuration here.
docker compose pull botapi
docker compose up -d --no-deps botapi
docker compose logs --tail=100 botapi
```

For a locally built installation, use the build override consistently:

```sh
docker compose -f docker-compose.yml -f docker-compose.build.yml stop botapi
# Back up ./data and private configuration before replacing the binary.
docker compose -f docker-compose.yml -f docker-compose.build.yml build botapi
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --no-deps botapi
```

Preserve `./data`, its ownership compatible with the selected server identity,
the API endpoint and local-mode settings. The default root bootstrap uses
`101:101`; a direct non-root server uses the configured Docker UID:GID.
Do not run two Bot API processes against one data directory. Restoring an old
image may also require a compatible state backup; image rollback alone is not
a guarantee.

After an update, check service logs and send a test message to a bot already
assigned to the server. Confirm the actual webhook URL, delivery status and
User-Agent in the receiving service's logs.

## Diagnostics

For Linux rootful Docker on a POSIX filesystem (`linux/amd64`), qualify a loaded
candidate with `python3 tools/check_runtime_permissions.py --image
botapi-candidate:check`. The runner uses only disposable named volumes and bind
directories outside the checkout, synthetic credentials and isolated Compose
services with no network or published ports. It checks default/root and direct
numeric/named users, restarts, existing data, separate write/search/read-only
failures, secrets and log permissions. It prints candidate metadata and separates
`REAL_BINARY` startup/HTTP checks from `ENTRYPOINT_FIXTURE` and `GROUP_FILESYSTEM`
simulations. Missing Docker, timeout or an omitted mandatory case fails the run.
Rootless/userns-remap, Docker Desktop and ARM64 are not qualified by this gate.

A stray nested file with incompatible ownership does not itself block startup.
The runner verifies its denied access and unchanged hash/owner/mode separately,
then adapts only its stopped test copy offline. The server does no recursive
audit or repair; the unrelated experimental `tools/ci_safety` startup policy is
not the contract of this gate. No real bot authorization or download is tested.

```sh
docker compose ps
docker compose logs --tail=100 botapi gateway
docker compose exec botapi telegram-bot-api --version
```

Remove tokens, API hashes, webhook secrets and sensitive URLs before sharing
logs. Separate infrastructure reachability from bot authorization and delivery.

## Documentation and contributions

Documentation lives in `docs/en` and `docs/ru`. Update both languages for
behavioral changes. The short root README links to these guides.

The Pages site uses Jekyll from the existing `main /` publishing source.
`_config.yml` supplies the project base path and navigation; `_layouts/default.html`
is the shared layout. Markdown links are rewritten for Pages by
`jekyll-relative-links`, while remaining usable on GitHub.

The original `tg_selfhost_botapi_migrator.html` URL remains available. Docs changes
are built in PRs without deployment; merging to `main` publishes through the
existing Pages integration.

[Contribution guide](../../CONTRIBUTING.md) ·
[Current work](https://github.com/ichinya/tg-selfhost-botapi/issues/19)

## Changing storage identity

Stop the single writer and all readers, then take a consistent backup preserving
owners and modes. Record the old and new UID:GID and the canonical storage root.
Adapt only the chosen tree offline, without following symlinks or crossing into
other mounts; inspect nested files and remaining old owners. Do not apply blanket
recursive permission changes to the state tree. For a new directory, a targeted
`install -d -m 0700 -o 1000 -g 2000 /srv/tg-selfhost-botapi/temp` is one example.
Prepare state and temp for the effective identity, ensure `_FILE` secrets are
readable and the log parent writable and searchable. Check actual create and
rename behavior; ACLs or setgid alone do not guarantee it. Start one writer and
verify new writes and old data before starting readers. Rolling back the image or
user is separate from restoring compatible ownership or a backup; never change
ownership of live state or run two writers.
