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
python3 -m unittest discover -s tools -p 'test_*.py' -v
API_ID=12345 API_HASH=test-placeholder docker compose config --quiet
```

Entrypoint tests require a POSIX environment. For image changes, check the patch
against the selected official revision and complete a Docker build and smoke test.
Use mock APIs and temporary data for migration tests.
Migrator export security tests require Python 3, Node.js 24, Bash and a POSIX
PTY. On Windows use Linux or WSL. Run the full discovery above, or run
`MIGRATOR_SECURITY_REQUIRED=1 python3 -m unittest discover -s tools -p 'test_migrator_plan.py' -v`.
An unsupported local platform may skip these tests; acceptance requires a pass
without skips in Linux CI. Use mock APIs and synthetic tokens only.

Update [English](docs/en/README.md) and [Russian](docs/ru/README.md) documentation
together. Keep the root README short. Documentation changes get a Jekyll build
and internal-link check in CI; the existing migrator URL must keep working.

## По-русски

Перед issue или PR проверьте существующие задачи. Укажите ревизию, тег/digest
образа, ожидаемое и фактическое поведение, шаги воспроизведения. Используйте
тестовые токены, очищайте журналы от секретов. Для кода выполните проверки выше;
для изменения поведения обновите обе версии документации.
Для проверки экспорта мигратора нужны Python 3, Node.js 24, Bash и POSIX PTY;
в Windows используйте Linux или WSL. Локальный пропуск не заменяет успешный
прогон Linux CI; применяйте только mock API и синтетические токены.
