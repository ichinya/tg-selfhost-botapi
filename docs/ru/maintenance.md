---
title: Обслуживание
translation: /docs/en/maintenance.html
---

# Обслуживание

## Сборка образа

Workflow проверяет официальный исходник tdlib и digest Alpine 3.22 каждую ночь
около **04:37 Asia/Yekaterinburg** (23:37 UTC), при изменении основной ветки и
вручную. GitHub может задерживать запуск по расписанию.

Ключ сборки учитывает source/base/platform identities, политику квалификации и
байты всех build/verification helpers. Все jobs используют один сохранённый snapshot.
Существующий тег требует сохранённого доверенного proof и новой нативной квалификации.
Только подтверждённый registry 404 допускает новую сборку; auth/network errors
останавливают выпуск.

Для нового образа workflow:

1. Проверяет применимость патча User-Agent к выбранной официальной ревизии.
2. Компилирует весь сервер.
3. На каждом native CPU проверяет ELF/config/version, штатный entrypoint/gateway и
   production webhook sender с negative control, ожидающим неверный UA.
4. Передаёт точные runtime/sender archives единственному publisher, проверяет полный
   index двух платформ, затем присваивает `build-<K>` и `latest` из его digest.

Отказ до promotion сохраняет прежний `latest`. Потерянный ответ записи означает
UNKNOWN до readback reconciliation. Из PR публикации нет. Компонентная проверка
sender не доказывает доставку через Telegram.

Для расписания и публикации workflow должен быть в основной ветке. Запись в GHCR
использует `GITHUB_TOKEN` с `packages: write`. После первого выпуска настройте
публичность пакета либо авторизацию клиентов.

## Обновление установки

Публикация в registry не перезапускает VPS. Выберите проверенный тег/digest через
`BOTAPI_IMAGE` в `.env`, затем:

```sh
docker compose stop botapi
# Здесь сделайте согласованную копию ./data и приватной конфигурации.
docker compose pull botapi
docker compose up -d --no-deps botapi
docker compose logs --tail=100 botapi
```

Для локальной сборки последовательно используйте build override:

```sh
docker compose -f docker-compose.yml -f docker-compose.build.yml stop botapi
# До замены бинарника сохраните ./data и приватную конфигурацию.
docker compose -f docker-compose.yml -f docker-compose.build.yml build botapi
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --no-deps botapi
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

## Контракт multi-platform

Snapshot фиксирует ровно `linux/amd64` и `linux/arm64`, source revision, Alpine index
и platform children, байты рецепта и policy. Сохранение:
`python3 tools/image_inputs.py --output snapshot.json`; проверка без нового resolution:
`--input snapshot.json --snapshot-hash <hash>`. JSON передаётся артефактом, CLI выводит
скалярные key=value. Кеш не заменяет qualification. Config ID, SHA256 архива, child
и index digest проверяются отдельно. ELF64 требует machine ID 62/183 и точный UA
marker. Release index содержит ровно две runnable platforms без attestations.

Native jobs проверяют CPU host/daemon, версию, ELF, штатный entrypoint и ownership,
точный direct/gateway JSON 404 (`ok:false`, `error_code:404`, `description:Not Found`)
в internal network. Target sender-test использует те же production objects;
receiver требует POST с nonce, единственный точный User-Agent и queue ACK. Negative
control с неверным ожидаемым UA обязан завершиться отказом. Runtime остаётся
последним/default target и не содержит driver/receiver.

Runner labels — `ubuntu-24.04` и `ubuntu-24.04-arm`; начальный бюджет 180 минут,
BUILD_JOBS=2. QEMU не служит fallback. Новые runtime builds cold, кеши разделены
по CPU/policy. Только publisher имеет packages:write. Он проверяет оба receipts,
точные runtime/sender archives и повторно ELF/config до candidate pushes. Полный
index проверяется до release writes; latest меняется одной операцией по digest.

Reuse требует proof успешной default-branch Actions compilation и новых native
runtime/sender checks. Отсутствие или истечение proof запрещает reuse/перезапись K.
Receipts хранятся 90 дней, архивы — два дня, sender image сохраняется в registry по
digest. Перед записью проверяется HEAD default branch. Потерянный ответ записи
требует readback, без blind retry или rollback. GHCR release не обновляет VPS.
APK mirror не закреплён, поэтому K не обещает побитовую пересборку.

Native builds, ARM runner, registry release/reuse/readback и свежая docs build:
NOTRUN локально, `verification deferred to CI/gates`. Apple Silicon, перенос старого
state и Telegram end-to-end требуют отдельных проверок.

Offline-приёмка: локально прошли 51 scoped-тестов (включая fault injection и patch regression), обе synthetic Compose config-проверки и `git diff --check`. Receipts сохраняют source revision, patch hash, чистые submodule identities и rootfs; проверяются размеры raw descriptors. Native cold/warm builds, registry integration/reuse/promotion, свежая Jekyll-сборка и post-merge release readback — NOTRUN: `verification deferred to CI/gates` (release readback: `verification deferred to CI/post-merge`). Локальный Docker build-check получил отказ доступа к внешнему buildx lock и не повторялся.
