---
title: Обслуживание
translation: /docs/en/maintenance.html
---

# Обслуживание

## Сборка образа

Workflow проверяет официальный исходник tdlib и digest Alpine 3.22 каждую ночь
около **04:37 Asia/Yekaterinburg** (23:37 UTC), при изменении основной ветки и
вручную. GitHub может задерживать запуск по расписанию.

Ключ сборки учитывает ревизии/digest, рецепт, entrypoint, патч и проверки образа.
Если соответствующий образ уже опубликован, компиляция пропускается.
Если проверка registry не подтвердила наличие образа, выполняется новая сборка.

Для нового образа workflow:

1. Проверяет применимость патча User-Agent к выбранной официальной ревизии.
2. Компилирует весь сервер.
3. Выполняет `--version`, проверяет строку заголовка в бинарнике и синтаксис entrypoint.
4. Публикует `ghcr.io/ichinya/tg-selfhost-botapi:build-<key>` и продвигает `latest`.

Ошибка проверки оставляет прежний опубликованный `latest`. Из PR публикации нет.
Наличие строки в бинарнике не заменяет проверку доставки реального webhook.

Для расписания и публикации workflow должен быть в основной ветке. Запись в GHCR
использует `GITHUB_TOKEN` с `packages: write`. После первого выпуска настройте
публичность пакета либо авторизацию клиентов.

## Обновление установки

Публикация в registry не перезапускает VPS. Выберите проверенный тег/digest через
`BOTAPI_IMAGE` и соответствующий `OBSERVER_IMAGE` в `.env`, затем:

```sh
docker compose stop observer botapi
# Здесь сделайте согласованную копию ./data и приватной конфигурации.
docker compose pull botapi observer gateway
docker compose up -d --force-recreate botapi observer gateway
docker compose logs --tail=100 botapi
```

Для локальной сборки последовательно используйте build override:

```sh
docker compose -f docker-compose.yml -f docker-compose.build.yml stop observer botapi
# До замены бинарника сохраните ./data и приватную конфигурацию.
docker compose -f docker-compose.yml -f docker-compose.build.yml build botapi observer
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --force-recreate botapi observer gateway
```

Сохраните `./data`, владельца `101:101`, endpoint и local mode.
Не запускайте два процесса Bot API с одним каталогом данных. Для возврата старого
образа может понадобиться совместимая резервная копия состояния: одного отката
бинарника недостаточно для гарантии.

После обновления проверьте журналы и отправьте тестовое сообщение боту,
который уже работает на этом сервере. Проверьте фактический webhook, состояние
доставки и User-Agent в журнале принимающего сервиса.

## Диагностика

```sh
docker compose ps
docker compose logs --tail=100 botapi gateway
docker compose exec botapi telegram-bot-api --version
```

Перед публикацией журналов уберите токены, API hash, webhook-секреты и
чувствительные URL. Разделяйте доступность инфраструктуры, авторизацию бота и
доставку обновлений.

## Документация и участие

Инструкции находятся в `docs/en` и `docs/ru`. При изменении поведения обновляйте
обе версии. Короткий корневой README ссылается на эти инструкции.

Pages использует Jekyll и уже настроенный источник `main /`. В `_config.yml`
заданы базовый путь и навигация, `_layouts/default.html` — общий шаблон.
`jekyll-relative-links` преобразует Markdown-ссылки для сайта, сохраняя их
работоспособность при чтении на GitHub.

Прежний URL `tg_selfhost_botapi_migrator.html` сохранён. Изменения документации
собираются в PR без публикации; после слияния в `main` их публикует действующая
интеграция Pages.

[Как участвовать](../../CONTRIBUTING.md) ·
[План работ](https://github.com/ichinya/tg-selfhost-botapi/issues/19)

### Предварительная диагностика doctor

`python3 tools/doctor.py --scenario official-to-self --format json` выводит
версионированный отчёт. Требуется Python 3.11 или новее. JSON и текст используют
одни коды: 0 READY, 1 BLOCKED, 2 ошибка вызова/входа, 3 UNKNOWN (включая внутренние ошибки сбора). READY
относится к предпосылкам миграции; авторизация и доставка требуют отдельных
проверок. Недостающие доказательства дают UNKNOWN. Процессы и HTTP без токена
разделяют бюджет (60 секунд, по 5 секунд на операцию). HTTP проверяет TLS,
не использует proxy, redirects или retries и читает не более 16 KiB. Отчёт
исключает сырые ответы и маскирует шаблоны секретов.

Процесс проверяется через `/proc` выбранного контейнера, включая эффективные
UID/GID/groups. Корневой HTTP-запрос должен вернуть 404 JSON с `ok:false` и целым
`error_code:404`; произвольного 404 недостаточно. Прямой bridge-запрос поддержан
для локального Linux Engine. Docker Desktop, remote engine, внешний proxy и
неоднозначные bindings оставляют соответствующие проверки UNKNOWN. Методы ботов
и облака не вызываются. Config ID образа, registry digests и версия бинарника
показываются отдельно; отсутствие digest локальной сборки не скрывается, pull
для его получения не выполняется.
Остановленный, paused, restarting, dead или unhealthy контейнер блокирует готовность;
ожидание health даёт UNKNOWN. Недоступный endpoint в поддержанной точке наблюдения
даёт BLOCKED; недоступная точка наблюдения оставляет UNKNOWN.
Разбор includes nginx дополняется независимой проверкой mounts. Случайный 404 не
доказывает изоляцию state. Alias на state или доступный state mount блокируют
готовность; штатные proxy и logging map поддерживаются. Doctor не перезагружает nginx.

### Регрессионные проверки doctor

Pure-тесты: `python3 -m unittest discover -s tools -p 'test_doctor*.py' -v` и
`python3 -m unittest discover -s tools -p 'test_check_doctor.py' -v`.
Отдельная команда `python3 tools/check_doctor.py` создаёт и удаляет только свой
случайный synthetic Compose project. Проверяются настоящий nginx, volumes,
runtime UID, только корневые HTTP-запросы и очистка probe. Harness может
скачивать/собирать тестовые образы; сам doctor только проверяет установку.
Версионные теги bases разрешаются в immutable registry digests перед запуском
harness и фиксируются в результате. Для воспроизведения задайте утверждённые
`DOCTOR_PYTHON_IMAGE` и `DOCTOR_NGINX_IMAGE`. Synthetic integration, smoke настоящего
образа, CI и production различаются. Пропущенный gate — NOTRUN, а не PASS.
Pure-регрессии также проверяют capacity выбранного поддерева self-to-self,
отказ при общем state, неизвестную совместимость и секреты-маркеры в обоих форматах.
Workflow doctor запускает unit-набор репозитория и проверку shell-синтаксиса
fixture перед отдельным synthetic Docker gate.

### Справочник оператора doctor

Выбирайте тот же упорядоченный набор Compose inputs, что использован при запуске:

```sh
python3 tools/doctor.py -f docker-compose.yml -f docker-compose.build.yml \
  --env-file /private/installation.env --project-directory /private/stack \
  -p installation --scenario official-to-self \
  --migration-input /private/decisions.json --format json
```

Profiles задаются повторяемым `--profile`. Для self-to-self добавьте отдельный
список `--source-file` и соответствующие `--source-env-file`, `--source-profile`,
`--source-project-directory`, `--source-project-name`. `--source-gateway-url`
относится только к сопоставленному source binding. Основной context — target;
для self-to-official это локальный source.

| Флаг / результат | Значение |
| --- | --- |
| `--gateway-url` | Выбранный published endpoint без credentials, query, fragment и bot path |
| `--timeout`, `--deadline` | Положительные секунды; по умолчанию 5 и 60 |
| `--no-write-probe` | Записи doctor отключены; write evidence UNKNOWN |
| `--min-free-bytes`, `--min-free-inodes` | Положительные пороги резерва; 1073741824 и 1024 |
| `--format text` / `json` | Одинаковое решение и exit; JSON — один документ в stdout |
| 0 / READY | Все обязательные предпосылки подтверждены |
| 1 / BLOCKED | Есть обязательное условие со статусом fail |
| 3 / UNKNOWN | Обязательные доказательства неполны, обязательных fail нет |
| 2 / UNKNOWN | Некорректный вызов или приватный вход |

Схема отчёта: `tools/doctor.schema.json`; входа: `tools/doctor-input.schema.json`.
Реальные входы и отчёты храните приватно вне VCS, docs и webroot. Токены и API hash
нельзя передавать аргументами CLI. Wildcard binding заменяется loopback;
несколько bindings требуют точного явного выбора. Непрозрачный reverse proxy
и deployment prefix пока дают `endpoint_mapping_unverified` и не запрашиваются.
Cloud HTTP, getMe, logOut, close, изменение webhook и миграция не выполняются.
После изменения контейнеров, mounts или config диагностику нужно повторить:
READY не подтверждает будущее состояние, Telegram session или Bash/browser executor.

JSON v1 использует `infrastructure`, `migration.executor_support` и проверки с `check_id` и `PASS|FAIL|UNKNOWN|SKIP`. Внутренние ошибки сохраняют прежние результаты; обязательный FAIL приоритетнее UNKNOWN. Пустые или пропущенные обязательные доказательства не подтверждают готовность.

Exit 2 также означает неверную конфигурацию Compose или отсутствие поддержки
Compose JSON. Недоступные Docker/daemon дают UNKNOWN/3. Exec для версии, процесса,
конфигурации и storage ограничены таймаутом внутри контейнера и общим бюджетом
хоста. Неподдерживаемая утилита timeout оставляет доказательства UNKNOWN.

При пустых registry metadata причина `local_build` используется только для
выбранного Compose build, иначе — `registry_digest_unavailable`. Запросов в registry нет.
`runtime_changed` инвалидирует зависимые доказательства при изменении container
identity, restart count, effective Compose или on-disk snapshot nginx.
При `quota_accounting_unverified` отдельно проверьте фактический quota headroom
для identity сервера. `unsafe_input_permissions` даёт BLOCKED/1; нечитаемый или
неверный private input — exit 2, непроверенная приватность платформы — UNKNOWN/3.

### Приватное досье миграции

Корневой helper хранит schema version 1 intent/receipt/summary в `logs/migration`
рядом со скриптом; права каталогов 0700, файлов 0600. Не размещайте их на публичном
хостинге: checker запрещает публикацию `logs`. Retention продолжается до ручного
удаления после reconciliation. Не прикладывайте raw и досье к публичным issue.
При аварии возможен приватный raw; обычно он удаляется только после успешной
очистки. Summary отмечает возможный retention при ошибке финализации.

Активный/stale lock, незавершённый intent, UNKNOWN запроса с токеном или частичная
миграция блокируют следующий запуск до HTTP. Остановитесь и проверьте независимые
данные; автоматического unlock, повтора и resume нет. Schema v1 — контракт для
явного будущего адаптера #2, а не финальный durable journal этой задачи. См.
[исходы и приватную диагностику](migration.md).
Для ручного восстановления остановите все helper, сопоставьте попытки с
независимыми данными и определите безопасную дальнейшую процедуру. Архивируйте
полное досье в приватном месте вне `logs/migration` до удаления проверенных
каталогов запусков и stale lock. Храните архив до разрешения ситуации. Нельзя
удалять lock ради повтора неизвестного запроса. Незавершённый probe без токена
и сохранившегося lock не блокирует запуск; незавершённые запросы с токеном блокируют.

## Схема операционного статуса v1

Observer выдаёт независимые наблюдения `process`, `migration`, `webhook`, `queue`,
`storage` и `image`. У каждого фиксированные source, state, reason,
UTC `observed_at` и возраст в секундах. Неизвестные числа равны null, а не нулю.
Готовность процесса не подтверждает завершение миграции или доставку webhook.
Публичная JSON schema: `tools/observability/status.schema.json`; неизвестные поля,
неверные целые, будущее время и слишком большой документ отклоняются.

## Host producer runtime

Диск и identity образа собирает доверенный host CLI на Python 3 вне HTTP observer.
Используйте те же project name/files, что при deployment:

```sh
python3 tools/observe_runtime.py --project-directory "$PWD" --file docker-compose.yml --file docker-compose.build.yml --watch
```

Подготовьте принадлежащий оператору `.observability/runtime` с правами 0755.
Атомарный status.json 0644 монтируется read-only; в нём нет путей, environment и
raw inspect. Producer выбирает ровно один Bot API, читает flags PID 1 и effective
UID/GID, metadata реальных work/temp, версию бинарника и actual image metadata,
после чего повторно проверяет identity контейнера. Неподдерживаемый custom image
даёт отказ. Одинаковые filesystem IDs work/temp нельзя суммировать.
Available inodes может быть null; capacity не проверяет quota или возможность записи.
У local build может не быть registry digest. Binary version, source revision,
build key, image ID и digest — разные поля. Без успешного producer они unknown,
через 90 секунд snapshot stale. Health от них не зависит.

Для supervision установите operator-owned systemd service с `Type=simple`,
`WorkingDirectory=/opt/tg-selfhost-botapi`, `ExecStart=/usr/bin/python3 /opt/tg-selfhost-botapi/tools/observe_runtime.py --project-directory /opt/tg-selfhost-botapi --file docker-compose.yml --file docker-compose.build.yml --watch`,
`Restart=on-failure`, `RestartSec=5`, `UMask=0077`; запускайте под доверенным
host account с Docker и включите `systemctl enable --now botapi-observation.service`.
Альтернатива — oneshot service с той же командой без --watch и timer с
`OnBootSec=30`, `OnUnitActiveSec=30`. Доступ к Docker даёт права на хост;
socket нельзя монтировать в observer. Ручной oneshot требует регулярного обновления.

## Приёмка пары кандидатов

Build key охватывает все Python modules observer, JSON schema, health helper и
Docker/Compose/nginx recipe. CI разрешает digest-pinned Python base observer,
загружает оба точных кандидата и проверяет общий build-key label. Reuse требует
повторной qualification; отсутствующий образ собирается, затем полная пара
проверяется до публикации. PR ничего не публикует. `build-<key>` и
`observer-build-<key>` — immutable входы deployment; latest aliases продвигаются
после gates, их продвижение не атомарно.

Изолированный gate запускается явно: `python3 tools/check_observability.py
--botapi-image botapi-candidate:check --observer-image observer-candidate:check`.
Он создаёт случайную internal Docker network, использует synthetic inputs,
проверяет mock privacy и реальные root/manager/helper, удаляет свои контейнеры.
`python3 tools/check_stats_source.py <upstream-checkout>` проверяет reviewed
фрагменты source точной revision кандидата; смена формата требует review.
Actual image build/smoke, POSIX producer/file gates, CI/Jekyll/Kuma и production
в этом Windows проходе не выполнялись: verification deferred to CI/gates.
Mock tests не доказывают privacy реального Bot API logging. Оставьте запросы
с токеном отключёнными до synthetic token privacy gate данного deployment
на поддерживаемом verbosity.

## Opt-in диагностика webhook

При пустом OBSERVER_REGISTRY опрос отключён. Для включения запустите host producer
и перенесите текущую `.image.instance` в приватный `registry.json` каталога
`.observability/registry` (0600, owner 101:101):

```json
{"schema_version":1,"enabled":true,"instance":"<64 hex characters from the fresh runtime snapshot>","allow_unobserved_migration":false,"bots":[{"alias":"public_label","credential_file":"bot.json"}]}
```

Сохраните `{"token":"<BOT_TOKEN>"}` в `.observability/credentials/bot.json`, 0600,
owner 101:101, задайте `OBSERVER_REGISTRY=/inputs/registry/registry.json`.
Aliases — публичные метки `[A-Za-z0-9][A-Za-z0-9_-]{0,31}`, без секретов.
Target фиксирован локальными bind/port Bot API. Cloud fallback и autodiscovery нет;
stats не служит источником credentials. При наличии migration producer задайте
`OBSERVER_MIGRATION_DIR=/inputs/migration`: опрос разрешают только свежие confirmed
finished операции. Без producer `allow_unobserved_migration=true` — отдельный явный
ownership opt-in; перед каждым переносом нужна пауза. Отключите `enabled`, подождите
минимум 60 секунд завершения текущих bounded requests и сделайте паузу до миграции.
Это не cross-host lock. Recreate меняет instance и отменяет прежнее подтверждение.
После перезапуска observer worker закрыт до первого более позднего runtime snapshot.
Обновите host metadata, сопоставьте миграцию, затем явно обновите instance и enabled.
Для rotation заменяйте приватные файлы атомарно; directory mounts видят rename.

Worker вызывает только getWebhookInfo каждые 60 секунд, до четырёх параллельно,
с deadline 2 секунды и без немедленного retry, включая 429. Публичны mode,
registered pending count, время/category исторической ошибки и synchronization
error time. URL/IP/headers/raw text не выдаются. Delivery остаётся not_observed.
Перед включением обязателен synthetic logging privacy gate actual image.

## Uptime Kuma

Создайте два HTTP(s) GET monitors на private management ingress:

- `Bot API liveness`: `http://127.0.0.1:18081/health/live`.
- `Bot API infrastructure readiness (HTTP handler / manager if enabled)`:
  `http://127.0.0.1:18081/health/ready`.

Для обоих: accepted status **только 200**, timeout **5 секунд**, heartbeat interval
**60 секунд**, retries **2**, redirects **off**. Без bot token и webhook secret.
Удалённая Kuma использует защищённый HTTPS ingress, VPN или tunnel со своим access
control. В контейнере Kuma 127.0.0.1 означает саму Kuma: укажите и проверьте доступный
ей private management hostname/port. Нельзя использовать raw 8082 и публиковать
8090. HTTP 200 `/status` не означает общий UP. Опциональные JSON checks должны
проверять нужную секцию и freshness схемы schema_version 1.

Интерпретация: process ready + migration unknown допустимы; историческая webhook
ошибка не означает текущий DOWN; рост sampled backlog — тренд нижней границы;
stats disabled означает неизвестную очередь, а не ноль; stale runtime означает
неизвестные диск/image для текущих решений. Polling mode не доказывает живой consumer.
URL, нулевая очередь, отсутствие ошибки и завершение миграции не подтверждают
доставку. Для этого нужны отдельно разрешённый update и evidence получателя.

Приёмка на изолированном deployment: запишите Kuma version, private endpoints и
settings; наблюдайте UP, остановите Bot API и получите DOWN, пересоздайте полную
пару и gateway и получите UP. Отдельно остановите observer, чтобы отличить его
отказ. Ручная приёмка настоящей Kuma в этом проходе NOTRUN.

## Обновление и rollback пары

Закрепите BOTAPI_IMAGE как `build-<key>`, OBSERVER_IMAGE как
`observer-build-<same-key>` либо точные digest. Сохраняйте project и Compose overrides:

```sh
docker compose pull botapi observer gateway
docker compose up -d --force-recreate botapi observer gateway
```

Для local builds используйте оба `-f docker-compose.yml -f docker-compose.build.yml`
при build/up. Пересоздавайте observer при смене владельца namespace и gateway для
обновления routing. Rollback выбирает прежнюю совместимую пару и ту же процедуру;
при необходимости нужна совместимая backup состояния. Обновление только botapi
с --no-deps неполно. Docker unhealthy — сигнал, а не автоматический restart или
recovery. После замены проверьте health, freshness источников и ownership.
