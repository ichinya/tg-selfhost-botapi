---
title: Maintenance
translation: /docs/ru/maintenance.html
---

# Maintenance

## Image pipeline

The image workflow checks official tdlib source and the Alpine 3.22 digest every
night around **04:37 Asia/Yekaterinburg** (23:37 UTC), on default-branch changes,
and on manual runs. GitHub may delay scheduled runs.

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

### Registry, build and startup failures

| Symptom | Class | Check / action and expected result |
| --- | --- | --- |
| Final `unauthorized` or `denied` | Authentication / permissions | Check registry, reference, package rights and same user/credential store as login; retry the intended pull with authorized access. |
| Repository, tag or digest missing | Reference | Check spelling and publication/visibility; select an existing reference. |
| `no matching manifest` | Platform | Compare host architecture with published platforms; select a supported image. |
| 429 pull rate limit | Pull quota | Check applicable Hub limits and wait for quota recovery; authorized access may change the applicable limit. |
| 429 abuse limit | Request frequency | Reduce request frequency and use backoff; login does not guarantee a fix. Do not deliberately exhaust limits. |
| DNS, timeout or TLS error | Network | Check daemon DNS, proxy, routing and trusted CA; host curl and daemon can use different paths. Restore connectivity and trust. Never disable TLS or use insecure registries as a workaround. |
| Cannot connect to daemon | Docker daemon | Check daemon status and user access; restore daemon access. |
| Registry 5xx | Registry service | Check registry status and retry later with backoff. |
| APK/GitHub failure or OOM during build | Build dependencies/resources | Inspect sanitized build output and resources; restore repository access or capacity before rebuilding. Hub login is not the remedy. |

A 401 challenge from registry `/v2/` can be normal; it alone is not an authentication failure. A successful host curl does not prove daemon pull works.

```sh
curl --connect-timeout 5 --max-time 10 -sS -D - -o /dev/null https://registry-1.docker.io/v2/
```

HTTP 401 with `WWW-Authenticate` is the expected challenge and indicates shell access to that endpoint, not access to an image. Test the intended pull separately. DNS, TLS, timeout and 5xx follow the network or service branches above; daemon context, DNS, proxy and CA may differ from the shell. No PAT is needed for this request.

For runtime, use `docker compose ps`, `docker compose logs --tail=100 botapi gateway` and `docker inspect --format 'name={''{.Name}} status={''{.State.Status}} exit={''{.State.ExitCode}} restarts={''{.RestartCount}} image={''{.Image}}' tg_botapi tg_gateway`. Check port conflicts, exit codes and restart loops; `TELEGRAM_API_ID is required` on immediate botapi exit indicates missing or unfilled `.env`. Compare container image IDs with the recorded IDs. HTML 404, 502/504 or wrong upstream fail the readiness contract: inspect gateway routing and logs. After replacing botapi repeat the gateway probe; if necessary restart gateway and repeat it, without assuming nginx has refreshed automatically.

Check data directory ownership and application credentials locally if startup fails. View logs locally and redact API hashes, tokens, webhook secrets and URLs before sharing. After recreation, nginx may retain an old upstream address: verify state and identity first, then restart the selected gateway if needed and repeat the probe.

After updating, repeat [binary, identity and readiness checks](getting-started.md#start), retaining the build override for local mode. Delivery to an assigned bot is a separate subsequent check.

A report should contain revision, Docker/Compose versions, architecture, mode, selected reference/digest, container image ID, stage, exit code and sanitized error. Exclude `.env`, Docker config, full container inspect and unredacted logs.
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
