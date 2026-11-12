---
title: Documentation
permalink: /docs/en/
translation: /docs/ru/
---

# TG Selfhost Bot API

Run the official Telegram Bot API server in Docker with an independent entrypoint,
a webhook User-Agent patch, and migration helpers.

## Guides

- [Getting started](getting-started.md) — install, build or pull an image, verify the service.
- [Configuration](configuration.md) — ports, environment variables, files and access.
- File access: split media + scoped RO volume, or the opt-in per-bot Bearer handler;
  [setup and trust boundary](configuration.md#files-in-local-mode).
- [Migration](migration.md) — cloud/local transitions and the current helper limitations.
- [Maintenance](maintenance.md) — image updates, backups, diagnostics and documentation.

[Русская версия](../ru/README.md) · [Browser migration tool](../../tg_selfhost_botapi_migrator.html)

## Components

| Component | Role |
| --- | --- |
| Official tdlib server | Bot API implementation |
| This project's image | Builds the server, applies the webhook patch and starts it from environment variables |
| nginx gateway | Forwards HTTP requests to the server |
| Doctor host CLI | Checks installation and migration prerequisites with safe text/JSON reports |
| Python executor | Sealed plan/apply/status/resume for all four migration directions |
| Bash helper | Compatibility adapter to the same executor |
| Browser tool | Same-origin loopback helper UI; Pages remains the entry screen |

The build does not depend on aiogram. Their project packages the same official
server; this repository maintains its own Docker packaging.

The image pipeline supports `linux/amd64`. Publication and scheduled builds require
the image workflow to be merged into the default branch and its first successful
release. A configured image name alone does not mean the image has been published.

Implementation work is tracked in [issues](https://github.com/ichinya/tg-selfhost-botapi/issues/19).
For protected credentials and diagnostics, see [configuration](configuration.md#docker-compose-file-secrets) and [migration](migration.md#protected-input-policy).
