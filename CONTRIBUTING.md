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

## Multi-platform release qualification / Проверка выпуска

Run the scoped offline contract and fault-injection suites on a dirty checkout:

```sh
python3 -m unittest tools.test_image_inputs tools.test_multiarch_verify tools.test_multiarch_qualify tools.test_multiarch_publish
```

PR CI must cold-compile both native CPUs, check ELF/config/version/normal startup,
the exact gateway signature, production sender and its wrong-UA negative control.
Only exact runtime/sender archives reach the publisher; no rebuild there. Test
missing/duplicate ARM, swapped config/ELF, wrong archive/policy/receipt, stale HEAD,
expired proof, auth errors and lost-write reconciliation with a fake registry.
Full POSIX discovery and fresh Jekyll/check_docs run in clean CI. Unavailable gates
are `verification deferred to CI/gates`; post-merge release readback is NOTRUN until
observed. Registry release does not deploy production.

На dirty checkout запускайте scoped-команду выше; полный POSIX discovery и свежие
Jekyll/check_docs выполняются в clean CI. Обязательны две native cold compilation,
ELF/config/version/штатный startup, точный gateway response, настоящий sender и
wrong-UA negative control. Publisher получает точные runtime/sender archives без
rebuild. Проверяйте missing/duplicate ARM, подмену config/ELF/archive/policy/receipt,
stale HEAD, expired proof, auth errors и потерянный ответ записи на fake registry.
Недоступные gates: `verification deferred to CI/gates`; post-merge readback — NOTRUN
до фактической проверки. Registry release не развёртывает production.

Webhook profile #7 gates: Node 24+, Python 3.13, Bash 4+, curl/jq/openssl, non-root POSIX.
Run the four explicit `tools.test_webhook_profile_*` modules listed in maintenance, then all tracked #10 tests and `test_webhook_user_agent`.
`node tools/embed_webhook_profile.cjs --check` verifies standalone helper/browser/export sync.
`check_issue7_sender.py --source` is a separate pinned-source gate, not unit discovery.
Receiver/manual POST, source assertions, actual image logs/nginx pass-through and live Telegram receipts are different evidence.
Unavailable execution: NOTRUN, verification deferred to CI/gates.


Проверки webhook-профиля #7: Node 24+, Python 3.13, Bash 4+, curl/jq/openssl и POSIX без root.
Запустите четыре модуля `tools.test_webhook_profile_*`, перечисленные в maintenance, затем все отслеживаемые тесты #10 и `test_webhook_user_agent`.
`node tools/embed_webhook_profile.cjs --check` проверяет синхронизацию standalone helper, браузера и экспорта.
`check_issue7_sender.py --source` — отдельная проверка pinned source, не часть unit discovery.
Receiver/manual POST, source assertions, логи реального образа/nginx и live Telegram receipts дают разные доказательства.
Недоступные проверки: NOTRUN, verification deferred to CI/gates.
