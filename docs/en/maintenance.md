---
title: Maintenance
translation: /docs/ru/maintenance.html
---

# Maintenance

## Image pipeline

The image workflow checks official tdlib source and the Alpine 3.22 digest every
night around **04:37 Asia/Yekaterinburg** (23:37 UTC), on default-branch changes,
and on manual runs. GitHub may delay scheduled runs.

Pair keys cover the resolved revision/base digests and real recipes, runtime,
fixtures, tests and documentation gates. Confirmed published candidates may be
pulled instead of rebuilt, but always pass current qualification again. A confirmed
missing manifest allows a build; UNKNOWN registry status stops qualification.

For every candidate pair it:

1. Checks that the User-Agent patch applies to the selected official revision.
2. Builds missing images with one compilation job and bounded builder resources.
3. Runs unit, CLI, context/privacy, Jekyll and synthetic file-contract gates,
   including the pinned TDLib offline probe and state isolation before/after opt-in.
4. Seals the exact Bot API/downloads image IDs in a checksummed archive.
5. Loads that archive without rebuilding, publishes both `build-<key>` images,
   checks registry digest/image-ID equality, then promotes their `latest` tags.

Failed qualification leaves the previously published `latest` in place. Pull
requests do not publish. Promotion of two registry tags is sequential, not an
atomic transaction; consumers should pin the qualified pair's digests. A binary
string check is not a live webhook-delivery test, and publication is not deployment.

The workflow needs to be on the default branch before the schedule/publication
can work. GHCR writes use `GITHUB_TOKEN` with `packages: write`. Configure package
visibility or client authentication after the first publication.

## Update an installation

Before enabling split storage, stop writer and readers and take one private cold
backup of state, media, image/configuration and ownership/ACLs. Never move binlogs
or all legacy state into media. Historical cache paths may remain under the old
state root and are rejected by the new readers; automatic cache conversion or
Telegram re-download is not guaranteed. Resume only after checking a new getFile
path and isolation. Rollback restores the matching backup, configuration and image
together while keeping state inaccessible to readers and proxies.

For an existing remote profile, first stop all readers and the writer (local
readers must finish and remain stopped). Make the backup outside both roots:

```sh
docker compose -f docker-compose.yml -f docker-compose.downloads.yml stop downloads downloads-gateway botapi
# BACKUP_DIR is an existing, private operator directory outside ./data and ./files.
sudo tar --numeric-owner --acls --xattrs -cpf "$BACKUP_DIR/storage.tar" data files
```

Back up `.env`, registry, token files and image digests privately alongside the
archive, preserving owner/mode/ACLs. Prepare only the new media/bot roots, start
the matching candidate pair and test exact bytes/hash, read-only access and
legacy-path denial before resuming clients. On rollback stop everything again,
restore that complete cold set (not a mixture of old state and new media), check
owners and keep the state root inaccessible. Synthetic fixture rehearsal covers
populated-layout bytes/ownership and rollback; it does not prove Telegram session
continuity or historical re-download. The separate pinned-source TDLib/tdutils
offline harness verifies downloaded-media create/rename and reader permissions.
Until its Linux run passes, that evidence is UNKNOWN and publication fails closed.

Registry publication does not restart your VPS. Select a tested tag/digest with
`BOTAPI_IMAGE` in `.env`, then:

```sh
docker compose stop botapi
# Make a consistent backup of ./data, ./files and private configuration here.
docker compose pull botapi
docker compose up -d --no-deps botapi
docker compose logs --tail=100 botapi
```

For a locally built installation, use the build override consistently:

```sh
docker compose -f docker-compose.yml -f docker-compose.build.yml stop botapi
# Back up ./data, ./files and private configuration before replacing the binary.
docker compose -f docker-compose.yml -f docker-compose.build.yml build botapi
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --no-deps botapi
```

Preserve `./data`, `./files`, ownership `101:101`, the API endpoint and local-mode settings.
Do not run two Bot API processes against one data directory. Restoring an old
image may also require a compatible state backup; image rollback alone is not
a guarantee.

After an update, check service logs and send a test message to a bot already
assigned to the server. Confirm the actual webhook URL, delivery status and
User-Agent in the receiving service's logs.

## Diagnostics

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
