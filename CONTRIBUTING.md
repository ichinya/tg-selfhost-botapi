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

## Gateway upload acceptance

Run separately from unit discovery, without Telegram credentials:

```sh
python3 -I -m unittest discover -s tools -p 'test_gateway_uploads.py' -v
python3 tools/check_gateway_uploads.py --profile quick --revision "$(git rev-parse HEAD)" --report /tmp/issue4-quick.json
python3 tools/check_gateway_uploads.py --profile full --revision "$(git rev-parse HEAD)" --report /tmp/issue4-full.json
python3 tools/check_gateway_uploads.py --profile slow --revision "$(git rev-parse HEAD)" --report /tmp/issue4-slow.json
python3 tools/check_gateway_uploads.py --profile storage --revision "$(git rev-parse HEAD)" --report /tmp/issue4-storage.json
timeout 2700 python3 tools/check_gateway_uploads.py --profile all --revision "$(git rev-parse HEAD)" --report /tmp/issue4-report.json
```

Prerequisites: Python 3.11+, Docker Compose with Linux containers, registry access,
writable temporary storage and space on Docker's backing filesystem. `quick`
(`fast` is a compatibility alias) tests 2/4 MiB uploads, scaled 8 MiB boundaries
and routing; `full` tests 2048 MiB ±1 byte and a 2000 MiB file. Reserve at least
10 GiB on both filesystems; sequential scenarios can write much more in total.
`slow` tests real pauses over 60 seconds and derived 2-second controls; `storage`
tests staging, worker permissions, cleanup, SIGKILL/recovery and bounded ENOSPC.
`all` requires every profile. NOTRUN and cleanup failures cannot pass acceptance.
Record unavailable checks as `verification deferred to CI/gates`.

`--nginx-image`/`GATEWAY_NGINX_IMAGE` and `--python-image`/`GATEWAY_PYTHON_IMAGE`
override pinned defaults; the runner records actual IDs/digests and config hashes.
Keep reports outside docs/webroot. The mock checks gateway transport; Telegram,
the actual Bot API image and VPS require their own acceptance.

In a dirty checkout use only the scoped suite. For full discovery on Linux/POSIX,
export a clean committed candidate to exclude unrelated untracked files:

```sh
candidate=$(mktemp -d)
git archive HEAD | tar -x -C "$candidate"
cd "$candidate"
timeout 180 python3 -m unittest discover -s tools -p 'test_*.py' -v
```

Use WSL/Linux or CI for POSIX tests; native Windows results do not replace them.
Integration has a separate 45-minute watchdog. Interrupted runs clean only their
exact owner label. CI repeats cleanup in an always-step and retains the report.

File-contract changes must preserve both direct/scoped RO reads and the per-bot
`POST /v1/files/download` boundary. Run scoped units for `test_file_access.py`,
`test_download_server.py`, `test_check_file_contract.py`, `test_check_docs.py`,
`test_entrypoint.py`, image inputs and doctor before the full clean-candidate suite.
Build `botapi-candidate:check` and `downloads-candidate:check`, then run:

```sh
python3 tools/check_file_contract.py --botapi-image botapi-candidate:check \
  --downloads-image downloads-candidate:check --report file-report.json
```

The full runtime gate uses only disposable synthetic storage and requires Linux
amd64/openat2. It records exact source hashes/image IDs. A denied/unavailable
Docker, kernel or Jekyll gate is NOTRUN (`verification deferred to CI/gates`), not
PASS. Never use production volumes or import unrelated untracked helpers to make
the gate pass. Retain the original migrator HTML bytes and exclude examples,
fixtures, media, secrets and runtime configuration from Pages.

`files.yml` runs the complete suite only on a clean checkout. `image.yml` qualifies
the exact Bot API/downloads IDs and current source hashes on both build and reuse
paths; publication follows the file and rendered-docs gates. `DOWNLOADS_RECIPE`
and the main recipe must include new runtime or qualification inputs before use.

## По-русски

### Приёмка загрузок gateway

Команды выше выполняются отдельно от unit discovery без credentials Telegram.
Нужны Python 3.11+, Docker Compose с Linux containers, registry, writable temp и
место на диске Docker. `quick` (совместимый alias `fast`) проверяет файлы 2/4 MiB,
малые границы 8 MiB и маршруты; `full` — 2048 MiB ±1 байт и файл 2000 MiB.
Резервируйте минимум 10 GiB на обеих файловых системах; суммарная запись за
последовательный прогон может быть намного больше. `slow` проверяет реальные
паузы больше 60 секунд и derived controls 2 секунды; `storage` — staging, worker,
cleanup, SIGKILL/recovery и ограниченный ENOSPC. `all` требует все профили.
NOTRUN и ошибки очистки не дают зелёный acceptance. Недоступные проверки
отмечайте `verification deferred to CI/gates`.

`--nginx-image`/`GATEWAY_NGINX_IMAGE` и `--python-image`/`GATEWAY_PYTHON_IMAGE`
заменяют закреплённые defaults; в отчёте сохраняются фактические IDs/digests и
hashes конфигурации. Храните отчёты вне docs/webroot. Mock подтверждает transport
gateway; реальный Bot API, Telegram и VPS требуют отдельной приёмки.
В dirty checkout запускайте scoped suite; для полного discovery экспортируйте
чистый `git archive HEAD`, как в примере выше. POSIX-тестам нужны WSL/Linux или CI;
нативный Windows их не заменяет. Watchdog integration — 45 минут, отдельно от
unit-бюджета 180 секунд. При прерывании очищаются только ресурсы точного owner
label; always-step CI повторяет очистку и сохраняет отчёт даже при сбое.

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
## Observability checks (issue #16)

On a dirty checkout use owned patterns; unrelated untracked suites are not release
evidence. On Linux/CI run:

```sh
python3 -m unittest discover -s tools -p 'test_observability*.py' -v
python3 -m unittest discover -s tools -p 'test_observe_runtime.py' -v
python3 -m unittest discover -s tools -p 'test_botapi_healthcheck.py' -v
python3 -m unittest discover -s tools -p 'test_doctor*.py' -v
python3 -m unittest discover -s tools -p 'test_check_doctor.py' -v
bash -n migrate_off_to_self.sh
sh -n tools/botapi_healthcheck.sh
python3 tools/check_stats_source.py /path/to/exact/upstream-checkout
python3 tools/check_observability.py --botapi-image botapi-candidate:check --observer-image observer-candidate:check
```

Helper and producer acceptance requires POSIX Bash, curl, jq and coreutils.
Windows skips are NOTRUN. Docker source/image/privacy, Jekyll and actual Kuma
gates are separate from Python unit results. Both release images must share one
build key and pass qualification before promotion. Never use real bot credentials
in fixtures or logs. Keep documentation paired in docs/en and docs/ru.


Webhook profile #7 gates: Node 24+, Python 3.13, Bash 4+, curl/jq/openssl, non-root POSIX.
Run the four explicit `tools.test_webhook_profile_*` modules listed in maintenance, then all tracked #10 tests and `test_webhook_user_agent`.
`node tools/embed_webhook_profile.cjs --check` verifies standalone helper/browser/export sync.
`check_issue7_sender.py --source` is a separate pinned-source gate, not unit discovery.
Receiver/manual POST, source assertions, actual image logs/nginx pass-through and live Telegram receipts are different evidence.
Unavailable execution: NOTRUN, verification deferred to CI/gates.

## Issue #17 privacy acceptance

In a shared dirty checkout run only `python3 -m unittest discover -s tools -p
"test_issue17_security_*.py"`; do not delete or adapt other untracked tests.
Full discovery requires a clean candidate containing the task's admitted files,
for example a detached worktree of the committed candidate. The CI checkout is
clean. Linux acceptance needs Python 3.11+, Node 24+, Bash, curl, jq, GNU coreutils,
Docker and non-root private-file tests. Explicit integration commands live in
`tools/issue17_security_gate.py`; unit discovery never starts Docker.

For secrets Compose models set both `TELEGRAM_API_ID_SECRET_PATH` and
`TELEGRAM_API_HASH_SECRET_PATH` to synthetic host files outside checkout; apply
secrets last, after the optional build overlay. Test Compose 2.24.4 and the CI
version. Evidence artifacts contain only status/counts, commit/revision, image
identity/build key and tool versions. Never upload raw logs, dossiers or inputs.
Unavailable runner/image/Pages checks are NOTRUN: verification deferred to CI/gates.
