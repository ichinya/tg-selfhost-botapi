---
title: Contributing
permalink: /contributing.html
translation: /docs/ru/maintenance.html
---

# Contributing

Bug reports and focused pull requests are welcome.
[Check existing issues](https://github.com/ichinya/tg-selfhost-botapi/issues) first.
Include the revision, image tag/digest, expected result, actual result and
reproduction steps. Use synthetic tokens and remove secrets from logs.

For runtime changes, run:

```sh
timeout 180 python3 -m unittest discover -s tools -p 'test_*.py' -v
API_ID=12345 API_HASH=test-placeholder docker compose config --quiet
```

Entrypoint tests require a POSIX environment. For image changes, check the patch
against the selected official revision and complete a Docker build and smoke test.
Use mock APIs and temporary data for migration tests.
On Windows, run `python3 tools/test_entrypoint.py` in WSL or CI; native Windows
discovery skips these POSIX-only tests. For module-based runs, set `PYTHONPATH=tools`.

Migration tests require Node.js 24+, Bash, curl and jq. They run the real helper
against loopback endpoints and the shipped page in a Node VM with intercepted
fetch; they do not use Telegram credentials. Keep an outer timeout as well as
the harness watchdogs. On a tree containing unrelated untracked tests, run only
`test_issue10_*.py`, `test_issue6_results.py` and the tracked regression tests; use full discovery in a clean
candidate or CI.

Issue #11 additionally requires GNU coreutils (`mktemp`, `date`, `stat`, `mkdir`,
`mv`, `chmod`, `rm`, `rmdir`, `cat`) and a non-root POSIX runner for permission
checks. In a dirty checkout, run only the owned suites:

```sh
python3 -m unittest discover -s tools -p 'test_issue11_*.py' -v
python3 -m unittest discover -s tools -p 'test_issue10_*.py' -v
```

The stateful mock is loopback-only and records remote effects before losing a
reply. Each independent scenario uses a fresh script/state root; recovery tests
intentionally reuse their root. For manual inspection, run
`python3 tools/issue11_http_mock.py --scenario lost --method logOut --state-file /private/mock-state.json`.
Use its printed loopback endpoints with the synthetic token from the fixture.
Keep private dossiers out of issues and artifacts. Full discovery in a clean
candidate and a fresh Jekyll build remain CI gates; Windows skips or denied
subprocesses are NOTRUN, never transport acceptance. Record unavailable gates as
`verification deferred to CI/gates` without delaying preparation of the PR.

On Windows use a full Git Bash path in `ISSUE10_BASH`; System32 `bash.exe` and
`wsl.exe` are rejected. Windows `timeout.exe` is a sleep utility. With Python
installed outside PATH, use (adjust the executable paths for your machine):

```powershell
$env:ISSUE10_BASH = 'C:/Program Files/Git/bin/bash.exe'
node tools/issue10_timeout.cjs 120 C:/ProgramData/miniconda3/python.exe -I -m unittest discover -s tools -p 'test_issue10_*.py' -v
```

POSIX unreadable-file tests require a non-root runner. A denied Bash launch is a
failed/unrun runtime check, never a successful migration test. A fresh Jekyll build
and `tools/check_docs.py` remain the documentation CI checks.

Doctor checks (no network/daemon in unit discovery):

```sh
python3 -m unittest discover -s tools -p 'test_doctor*.py' -v
python3 -m unittest discover -s tools -p 'test_check_doctor.py' -v
sh -n tools/doctor_fixtures/entrypoint.sh
python3 tools/check_doctor.py
```

The last command is an explicit synthetic Docker integration and may pull/build
test images. It cleans only its random project. Record unit, synthetic integration,
actual-image smoke, CI and production results separately; unavailable gates are
NOTRUN. Never put real migration-input files or diagnostic reports in docs/webroot.
Doctor reports follow `tools/doctor.schema.json`; private decisions use input v1.
Check exit codes 0/1/2/3 and keep internal collection failures separate from usage
errors. Run from a clean candidate without untracked helpers or `tools/__init__.py`.

Migration acceptance uses Python 3.11+ and Node 24 on Linux:
`python3 tools/check_migration_safety.py --require-posix` and
`node --test tools/test_migration_ui.mjs`. The dedicated workflow also exercises
only labelled fixture volumes, never a production bot. Windows passes are not
POSIX/volume acceptance. A browser timeout is tested separately from lost Bot API
responses. No live credentials or inference are used by these fixtures.

Приёмка миграции: Python 3.11+, Node 24 и Linux, команды выше. Проверки используют
mock APIs и временные volumes с точными IDs/labels. Windows-прогон не заменяет
POSIX/volume-приёмку; потеря ответа UI и Bot API проверяются отдельно.

Update [English](docs/en/README.md) and [Russian](docs/ru/README.md) documentation
together. Keep the root README short. Documentation changes get a Jekyll build
and internal-link check in CI; the existing migrator URL must keep working.

## По-русски

В Windows выполняйте `python3 tools/test_entrypoint.py` в WSL или CI: нативный
запуск Windows пропускает POSIX-тесты. Для запуска модулей задайте `PYTHONPATH=tools`.

Перед issue или PR проверьте существующие задачи. Укажите ревизию, тег/digest
образа, ожидаемое и фактическое поведение, шаги воспроизведения. Используйте
тестовые токены, очищайте журналы от секретов. Для кода выполните проверки выше;
для изменения поведения обновите обе версии документации.
Для тестов мигратора нужны Node.js 24+, Bash, curl и jq. Все запуски ограничивайте
внешним таймаутом. В Windows задавайте полный путь Git Bash через `ISSUE10_BASH`;
WSL-лаунчеры запрещены. Команда выше использует доступный Python вне PATH.
На дереве с чужими untracked-тестами запускайте `test_issue10_*.py`, `test_issue6_results.py` и отслеживаемые
регрессии; полный discovery выполняйте на чистом кандидате или в CI. Запрет запуска
Bash не считается успешной проверкой. Проверка нечитаемого файла требует POSIX
и непривилегированного пользователя; Jekyll и проверка ссылок выполняются в docs CI.

Для #11 также нужны GNU coreutils (`mktemp`, `date`, `stat`, `mkdir`, `mv`,
`chmod`, `rm`, `rmdir`, `cat`); запускайте обе scoped-команды выше. Mock работает
только на loopback и записывает remote effect до потери ответа. Независимые
сценарии используют свежие копии скрипта и state root; повторное использование
досье допускается только в тестах восстановления. Команда ручного mock приведена
выше; используйте напечатанные адреса и синтетический токен из fixture.
Приватные досье не прикладывайте к issue и артефактам. Полный discovery на чистом
кандидате и свежая сборка Jekyll проверяются в CI; Windows skip и запрет запуска
процесса — NOTRUN. Недоступные проверки отмечайте
`verification deferred to CI/gates`, продолжая подготовку PR.

Для doctor выполните обе unit-команды выше (им не нужен Docker/network).
`python3 tools/check_doctor.py` отдельно запускает synthetic Docker integration:
возможны pull/build тестовых образов, очистка ограничена случайным project.
Отдельно отмечайте unit, synthetic integration, smoke настоящего образа, CI и
production; недоступный gate — NOTRUN. Реальные migration-input и отчёты нельзя
помещать в docs/webroot. Для docs выполните Jekyll build и затем
`python3 tools/check_docs.py .site-check`; исходный HTML мигратора не меняйте.
Проверяйте схему отчёта, вход v1, exit codes 0/1/2/3 и shell-синтаксис fixture.
Запускайте тесты на чистом candidate без чужих helpers и `tools/__init__.py`;
внутренние ошибки сбора должны отличаться от неверного вызова.

## APK refresh regression (#23)

Python 3.11+ is required for the image tooling. In a dirty checkout, run only the
owned suites (set `PYTHONPATH=tools` for module runs):

```sh
python3 -m unittest tools.test_image_inputs tools.test_apk_docker_contract tools.test_image_metadata tools.test_apk_candidate tools.test_apk_refresh
```

On a clean candidate/CI run the full discovery with the existing outer timeout.
The explicit Docker integration is separate from unittest discovery:

```sh
python3 tools/image_inputs.py --json-out .build-inputs.json --build-env-out .env.build
python3 tools/check_apk_refresh.py --inputs .build-inputs.json --output evidence/apk-refresh.json
```

The restored fixture uses the documented Dockerfile-copy fallback: production
installation RUNs remain unchanged; an isolated context preinstalls the signed
synthetic v1 package before refresh. This keeps test trust material out of the
production Dockerfile. A/A must reuse both layers; after repository v2, the old-ID
control remains v1 and a new generation upgrades both branches and consumers.
Separate variants remove each stage's refresh consumption and must be detected.
No global cache prune, `--allow-untrusted`, or cache bypass is used. The runner owns
one bounded builder and temporary signing key; private keys never enter artifacts.
Docker integration, actual-image smoke, Jekyll, CI and security gates unavailable
locally are `verification deferred to CI/gates`, never PASS.

Для #23 используйте Python 3.11+ и scoped-команду выше в dirty checkout; полный
discovery — только на чистом candidate/CI с внешним timeout. Явная Docker-команда
проверяет подписанный fixture, A/A/cache control/B и отдельные отрицательные
варианты обеих стадий. Восстановлен fallback с копией Dockerfile во временном
context: production RUN не изменяется, тестовый trust не входит в production.
Недоступные integration/smoke/Jekyll/CI/security — `verification deferred to CI/gates`.

Webhook profile #7 gates: Node 24+, Python 3.13, Bash 4+, curl/jq/openssl, non-root POSIX.
Run the four explicit `tools.test_webhook_profile_*` modules listed in maintenance, then all tracked #10 tests and `test_webhook_user_agent`.
`node tools/embed_webhook_profile.cjs --check` verifies standalone helper/browser/export sync.
`check_issue7_sender.py --source` is a separate pinned-source gate, not unit discovery.
Receiver/manual POST, source assertions, actual image logs/nginx pass-through and live Telegram receipts are different evidence.
Unavailable execution: NOTRUN, verification deferred to CI/gates.
