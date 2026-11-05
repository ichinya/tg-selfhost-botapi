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
`test_issue10_*.py` and the tracked regression tests; use full discovery in a clean
candidate or CI.

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
На дереве с чужими untracked-тестами запускайте `test_issue10_*.py` и отслеживаемые
регрессии; полный discovery выполняйте на чистом кандидате или в CI. Запрет запуска
Bash не считается успешной проверкой. Проверка нечитаемого файла требует POSIX
и непривилегированного пользователя; Jekyll и проверка ссылок выполняются в docs CI.
