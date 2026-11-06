---
title: Maintenance
translation: /docs/ru/maintenance.html
---

# Maintenance

## Image pipeline

The image workflow checks official tdlib source and the Alpine 3.22 digest every
night around **04:37 Asia/Yekaterinburg** (23:37 UTC), on default-branch changes,
and on manual runs. GitHub may delay scheduled runs.
The image workflow also runs the required migrator security tests; see
[Contributing](../../CONTRIBUTING.md) for their dependencies.

The build key covers the resolved revisions/digests and the recipe, entrypoint,
patch and image tests. If the corresponding published build exists, compilation
is skipped. If registry inspection cannot confirm it, the pipeline rebuilds.

For a new build it:

1. Checks that the User-Agent patch applies to the selected official revision.
2. Compiles the entire server.
3. Runs `--version`, checks the header string in the binary and validates entrypoint syntax.
4. Publishes `ghcr.io/ichinya/tg-selfhost-botapi:build-<key>` and promotes `latest`.

Failed checks leave the previously published `latest` in place. Pull requests do
not publish. A binary string check is not a live webhook-delivery test.

The workflow needs to be on the default branch before the schedule/publication
can work. GHCR writes use `GITHUB_TOKEN` with `packages: write`. Configure package
visibility or client authentication after the first publication.

## Update an installation

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

Preserve `./data`, ownership `101:101`, the API endpoint and local-mode settings.
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
