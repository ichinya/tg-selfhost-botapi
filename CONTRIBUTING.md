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

Update [English](docs/en/README.md) and [Russian](docs/ru/README.md) documentation
together. Keep the root README short. Documentation changes get a Jekyll build
and internal-link check in CI; the existing migrator URL must keep working.

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
