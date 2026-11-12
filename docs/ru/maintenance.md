---
title: Обслуживание
translation: /docs/en/maintenance.html
---

# Обслуживание

## Смена identity сервера

Перед сменой ID остановите writer и автоматические перезапуски. Создайте
согласованную резервную копию с числовыми владельцами и правами. Проверьте
отдельные абсолютные пути, символические ссылки и чужие mounts; подготовьте
offline-копию под новые UID/GID и проверьте вложенные binlog и session, а не
только корневой каталог. Проведите storage smoke и запустите одного writer.
Для rollback сохраните старую копию с прежними ID и совместимым образом. Не
меняйте рекурсивно права работающей или общей базы. Старые кешированные пути
автоматически не переносятся.

Подготовьте state и HTTP temp под фактическую identity сервера. Bind mount,
именованный том и tmpfs имеют собственные владельца и права; права слоя образа
не исправляют mount. Новые файлы получают effective UID; без наследования файловой
системы GID берётся из основной группы, а setgid или ACL могут его изменить.
Umask `0027` ограничивает новые права, но не добавляет групповое чтение и не
меняет существующие файлы. Досье миграции остаются доступными только владельцу.
При прямом non-root запуске Docker сохраняет дополнительные группы. Для другого
UID используйте ограниченное RO-поддерево media из инструкции установки.

## Раздельное хранилище

Для split storage нужно окно обслуживания: остановите клиентов и writers,
согласованно сохраните private state и конфигурацию, затем включите files override.
Создаётся новый media cache; старые загрузки и сохранённые абсолютные пути
автоматически не переносятся. Legacy storage остаётся приватным; повторите getFile
для сохранённых file_id. Identity и реальные modes TDLib проверяются на конкретном
образе; исходники и unit-проверки не подтверждают права production.


Doctor проверяет persistence split media и разделение private backings без
скачивания реальных файлов. Optional handlers и consumer mapping остаются UNKNOWN;
нужен независимый synthetic file gate и проверка развёрнутого mapping.

## Приёмка миграции

Обязательный Linux/Node 24 mock-gate описан в CONTRIBUTING: потеря ответа до/после
эффекта, per-bot lock, crash вокруг intent/receipt, паритет планов интерфейсов,
доступ к helper и потеря ответа UI. Volume-gate использует только точные
fixture IDs/labels. CI проверяет tracked зависимости и отсутствие приватных
файлов в сайте. Платформенные skips не являются приёмкой. Старые curl-specific
assertions сохранены как справочный код; исполняемые тесты адаптера проверяют
тот же loopback protocol/journal, что CLI. Отсутствующий delivery-action fixture
issue #9 остаётся отдельным declared workspace baseline.

После перезапуска helper нужны новый session code и private runtime inputs.
Сохраняйте прежний журнал/ключ. Browser disconnect не отменяет фоновую задачу.
Прочитайте status/job result, заново подайте credentials перед resume.
Locator операции не является полномочием.

## Восстановление журнала миграции

Сохраняйте весь приватный каталог **вместе с `binding.key`**, когда операции
не выполняются. Восстанавливайте оба с владельцем и приватными правами.
Потеря ключа, смена токена, повреждение или неизвестная версия state блокируют
продолжение. Незавершённый intent становится UNKNOWN. Верните исходный журнал
и сверяйте ту же операцию; пустой state root не доказывает отсутствие эффекта.

После timeout UI сначала прочитайте offline status той же операции. Потеря
ответа только браузером не отменяет durable receipts. При потере ответа Bot API
сверьте UNKNOWN по trusted provider receipt с точными operation/digest/attempt,
endpoint/token bindings и временем. Без доказательств сохраняйте блокировку.
Изменение токена/deployment/профиля требует разбора и проверки с сохранением
исходного журнала; подтверждённую историю нельзя стирать.

## Сборка образа

Build key Bot API включает resolved revisions/digests и file-contract recipe,
tests/configs. У downloads отдельный key с immutable Python base. Даже если Bot API
переиспользуется из registry, текущий file gate проверяет точную пару образов снова.
После gate и проверки Pages публикуются `tg-selfhost-botapi:build-<key>` и
`tg-selfhost-botapi-downloads:build-<downloads-key>` в GHCR, затем без пересборки
продвигаются их `latest`.

Отдельный `files.yml` выполняет полный unit discovery на чистом checkout, Compose
combinations, state isolation, local/TLS/security integration и docs checks.
Недоступные локальные runtime-проверки — `verification deferred to CI/gates`;
для публикации CI обязан их пройти. Публикация не развёртывает и не проверяет VPS.

Workflow проверяет официальный исходник tdlib и digest Alpine 3.22 каждую ночь
около **04:37 Asia/Yekaterinburg** (23:37 UTC), при изменении основной ветки и
вручную. GitHub может задерживать запуск по расписанию.

Ключ сборки учитывает ревизии/digest, рецепт, entrypoint, патч и проверки образа.
Если соответствующий образ уже опубликован, компиляция пропускается; candidate
скачивается по digest и проходит проверку заново. Acceptance scripts, fixtures,
оба storage override и их тесты включены в ключ сборки.
Если проверка registry не подтвердила наличие образа, выполняется новая сборка.

Для нового образа workflow:

1. Проверяет применимость патча User-Agent к выбранной официальной ревизии.
2. Компилирует весь сервер.
3. Выполняет `--version`, проверяет строку заголовка в бинарнике и синтаксис entrypoint.
4. Проверяет выбранную ревизию исходников и TDLib submodule: download modes
   `0640/0750`, внутренний media temp и rename.
5. Проверяет точный image ID матрицей non-root storage и существующим migration
   volume gate.
6. Собирает downloads, проверяет точную пару через synthetic local/TLS/security
   matrix и actual startup без сети, сохраняет IDs/source hashes и проверяет Pages.
7. Публикует проверенные Bot API/downloads `build-<key>` и продвигает их `latest`
   без пересборки. Повторно используемые сборки также проходят все проверки.

Ошибка проверки оставляет прежний опубликованный `latest`. Из PR публикации нет.
Наличие строки в бинарнике не заменяет проверку доставки реального webhook.

Для расписания и публикации workflow должен быть в основной ветке. Запись в GHCR
использует `GITHUB_TOKEN` с `packages: write`. После первого выпуска настройте
публичность пакета либо авторизацию клиентов.

## Квалификация non-root candidate

Для локального rootful Linux Docker Engine с POSIX filesystem, Python 3.11+
и актуальным Compose v2 запустите проверки явно собранного candidate:

```sh
python3 tools/check_nonroot_compose.py --deadline 120
python3 tools/check_nonroot.py --image <candidate> --deadline 1200
python3 tools/check_migration_volumes.py --require-docker --image <candidate> --receipt /tmp/migration-volume-gate.json
```

Runner использует случайные ресурсы с labels, изоляцию сети, synthetic credentials,
ограниченные сроки вызовов и проверку владельца перед очисткой. Матрица проверяет
root bootstrap в `101:101`, явные `101:101`, `1000:1000`, `1000:2000` без passwd
entry, дополнительные группы, PID 1 и token-free HTTP, migration evidence, новые
и подготовленные bind/named volumes, restart/recreate, сохранность canary, denied
и read-only state/temp, чужого владельца, групповой доступ и недоступный binlog,
который сервер действительно открывает. Compose проверяется по production files:
отсутствующие inputs, aliases backing и `base+files` без non-root слоя отклоняются.

Media fixture проверяет inode/GID/modes при внутреннем temp-to-final rename,
ограниченный RO-доступ другого UID, запрет POSIX-записи отдельно от RO mount и
отказ чужой группе. Download temp на другом mount отклоняется. Synthetic fixture
подтверждает рецепт прав; source assertions сверяются с выбранной ревизией в CI.
Эти проверки не подтверждают реальную загрузку Telegram. Unit-тесты не запускают
Docker; real-image acceptance, CI и production — отдельные наблюдения. Недоступные
проверки — NOTRUN: verification deferred to CI/gates. Для Docker Desktop,
rootless/user namespaces и сетевых filesystem нужна отдельная квалификация.
Не запускайте harness с production mounts.

## Обновление установки

### Включение split storage и откат

1. Остановите клиентов, downloads, writers Bot API и supervisors, которые их
   перезапускают. Согласованно сохраните private state, identity образа, Compose/env,
   secret files и отдельно media для уже разделённой установки.
2. В окно обслуживания включите non-root и `docker-compose.files.yml` с проверенным образом
   и конфигурацией. Не копируйте state/binlogs в media и не исправляйте пути TDLib
   DB вручную. По умолчанию переход создаёт новый media cache. Подготовьте media source
   для настроенных UID/GID по инструкции установки; Compose требует существующий каталог.
3. Повторите getFile по сохранённым file_id. Перед доступом consumers проверьте
   новую media subtree, bytes/digest, ownership и mapping. Если upstream вернул
   старый private path, оставьте отказ и разберитесь в причине; доступ к state
   расширять нельзя. Сохранность старого cache/path не обещается. Холодный перенос
   с сохранением путей требует отдельной проверки выбранной upstream-версии.
4. Для rollback остановите новых writers и восстановите совместимые image,
   конфигурацию, private state и прежний layout из согласованного backup. Одного
   отката образа недостаточно. При self-to-self снимки media и state согласуются.

Не меняйте права cache рекурсивно и не открывайте его всем. Проверьте реальные
TDLib modes и настроенные UID/GID writer; reader использует ту же identity либо отдельно
проверенную read/traverse ACL. Каждому reader/handler — одна RO subtree, без parent,
соседних ботов, private temp/log/secrets и nested mounts. Local API и writer
доверенные; взаимно недоверенным операторам нужны отдельные instances/storage.

Для ротации замените защищённый Bearer-файл и перезапустите downloads. Проверьте
401 со старым credential и synthetic bytes с новым. Cache eviction, I/O timeout
30 секунд и общий deadline могут прервать передачу; Range/resume и retention SLA
не обещаются. Не вставляйте token-bearing paths в отчёты.

Публикация в registry не перезапускает VPS. Выберите проверенный тег/digest через
`BOTAPI_IMAGE` ? ??????????????? `OBSERVER_IMAGE` в `.env`. Каждая команда обновления должна использовать ровно тот
же набор файлов Compose в том же порядке, что и установка. Выберите `COMPOSE_FILES`:

```sh
# base
COMPOSE_FILES='-f docker-compose.yml'
# base + build
COMPOSE_FILES='-f docker-compose.yml -f docker-compose.build.yml'
# base + nonroot
COMPOSE_FILES='-f docker-compose.yml -f docker-compose.nonroot.yml'
# base + nonroot + files
COMPOSE_FILES='-f docker-compose.yml -f docker-compose.nonroot.yml -f docker-compose.files.yml'
# base + nonroot + build
COMPOSE_FILES='-f docker-compose.yml -f docker-compose.nonroot.yml -f docker-compose.build.yml'
# base + nonroot + files + build
COMPOSE_FILES='-f docker-compose.yml -f docker-compose.nonroot.yml -f docker-compose.files.yml -f docker-compose.build.yml'
```

Выберите только одну строку выше. Без слоёв nonroot/files identity сервера
вернётся к `101:101`, состояние подключится из `./data`, а media mount исчезнет.
Для установки из registry:

```sh
docker compose $COMPOSE_FILES stop observer botapi
# Сделайте согласованную копию фактического источника состояния и приватной конфигурации.
docker compose $COMPOSE_FILES pull botapi observer gateway
docker compose $COMPOSE_FILES up -d --force-recreate botapi observer gateway
docker compose $COMPOSE_FILES logs --tail=100 botapi
```

Для локальной сборки замените `pull` на `build` с теми же выбранными файлами.
Сохраните фактический источник состояния (`$BOTAPI_STATE_SOURCE` для nonroot,
`./data` для базовой модели), владельца выбранной identity сервера (по умолчанию `101:101`),
endpoint и local mode.
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

Postflight делает два чтения target через две секунды с общим deadline десять секунд. Сверяются точный URL, множество updates, connections, наличие сертификата и fixed IP. DNS IP — наблюдение. Тренд очереди и исторические/новые delivery/synchronization errors выводятся отдельно, только безопасными счётчиками. Пустая очередь не доказывает доставку. WebhookInfo не проверяет байты секрета и сертификата. Новые ошибки, отсутствующие счётчики или несовпадения останавливают приёмку; мутации не повторяются.

## Независимый receipt webhook и sender gate

Используйте отдельного test-bot и обработчик. Ожидаемый секрет задайте через защищённый environment либо WEBHOOK_SECRET_TOKEN_FILE вне checkout/webroot:

~~~sh
python3 tools/webhook_profile_receiver.py --expected-update-id 701 --seconds 60
~~~

Receiver слушает только loopback; для реального test-bot подключите свой контролируемый TLS test reverse proxy. Выбранный loopback_port выводится при старте. Ручной synthetic POST проверяет только приём обработчиком: отсутствующий/неверный/дублирующий secret header получает 403, посторонний update_id — 409. Receipt содержит только update_id, time, secret_matched, count. Храните receipt вне webroot и сопоставляйте update_id с новым событием test-bot; WebhookInfo и посторонний receipt не подтверждают доставку. Загружать можно публичный сертификат; test private key остаётся вне exports/repository.

Явный source gate проверяет закреплённую BOT_API_REVISION и реальный условный header в WebhookActor после применения tracked patches/webhook-user-agent.patch:

~~~sh
python3 tools/check_issue7_sender.py --source /path/to/pinned/telegram-bot-api
~~~

CI получает точную ревизию, никогда master. Source assertion не является runtime-доставкой. Изолированный C++ sender harness — NOTRUN без отдельной сборки из тех же исходников; реальный test-bot update с коррелированным receipt — третий уровень проверки конкретного развёртывания. Для unit-тестов receiver реальные Telegram credentials не нужны.

## Гейты квалификации профиля

Запуск: `timeout 420 python3 -m unittest tools.test_webhook_profile_contract tools.test_webhook_profile_ui tools.test_webhook_profile_transport tools.test_webhook_profile_receiver -v`, `PYTHONPATH=.:tools`, Node 24+, Bash 4+, curl, jq, openssl и непривилегированный POSIX runner. 22 общих fixtures исполняют shipped inline resolver и Bash jq program; реальные HTTP-тесты разбирают urlencoded/multipart, запускают helper/export, отклоняют readback mismatch и проверяют receipts. Privacy canaries охватывают вывод, clipboard, public state, отражённые API errors и curl argv. Scoped workflow запускает ту же матрицу и регрессии #10; pinned-source sender выделен в отдельный job. Чужие untracked issue7 drafts и workflow с Node 20 не подключаются.

Image/default upstream logger qualification, multipart через shipped nginx, C++ sender harness, Jekyll rendered checks и реальная Telegram delivery остаются явными внешними гейтами. Недоступный запуск — NOTRUN: verification deferred to CI/gates. Собственные сборки используют issue17-v1 fixed log projection до file/memory storage; перед deployment проверьте точный image.

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

## Изолированный пример с mock-сервером

Используйте Linux/WSL и loopback-only fixture ниже. Он не может обратиться
к Telegram. Для каждого сценария запускаются новые fixture servers/state;
это не способ восстановления реального бота. Перед запуском задайте
`MIGRATION_FIXTURE_DIRECTION` одним из четырёх direction names. Завершите
проверку за TTL evidence (пять минут), иначе перезапустите изолированный fixture.

```sh
umask 077
PYTHONPATH=tools python3 - <<'PY'
import json, os, tempfile
from pathlib import Path
from migration_mock import Bot, TOKEN, deployment
from migration_helper import Application, Server, write_bootstrap
root = Path(tempfile.mkdtemp(prefix="botapi-fixture-"))
source, target = Bot("source"), Bot("target")
direction = os.environ.get("MIGRATION_FIXTURE_DIRECTION", "cloud_to_local")
endpoint = source.endpoint if direction == "webhook_only" else target.endpoint
evidence = root / "deployment.json"
record = deployment(endpoint)
record["local_mode"] = direction != "local_to_cloud"
evidence.write_text(json.dumps(record))
evidence.chmod(0o600)
app = Application({"state_dir": str(root / "state"), "allowed_endpoints": [source.endpoint, target.endpoint],
                   "evidence_file": str(evidence), "trust_file": None, "fixture": True})
server = Server(app, 8765)
pairing = root / "pairing-code"
write_bootstrap(pairing, server.bootstrap, [root / "state"])
print("Synthetic fixture only:", server.origin, "private pairing file:", pairing, flush=True)
print("Synthetic source/target ready; private inputs withheld", flush=True)
print("Retained fixture authority:", root, flush=True)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close(); app.close(); target.close(); source.close()
PY
```

1. Прочитайте одноразовый код приватно из pairing-файла. Укажите напечатанные endpoints/token,
   соответствующие direction/mode, явный polling и quiescence JSON `"fixture"`.
   Для Local → Cloud также отметьте queue acknowledgement и cooldown 0.
2. Plan, проверка digest, Apply. Source detach предшествует target authorization.
   Миграция остаётся partial до endpoint/start checkpoints.
3. Введите `"fixture"` в endpoint-change и application-start receipts, затем
   Resume. Delivery остаётся NOTRUN до отдельного receiver receipt.
4. В Local → Local выполнение сначала остановится после close. Fixture transfer
   receipt требует точных operation_id/digest/close_attempt/source_fingerprint/
   target_fingerprint, target_deployment равного deployment fingerprint плана,
   совпадающих 64-hex source_manifest/target_manifest, 64-hex source_deployment,
   uid/gid 1000, текущего observed_at и true source_closed/no_writers/layout_valid.
   Это проверка границы аттестации, а не реальный перенос каталога TDLib.
5. Обновите вкладку и прочитайте status. Повторный Resume не увеличивает counters
   подтверждённых мутаций. Потерю ответов отдельно внедряют автоматические тесты.

Реальные providers задаются в private `MIGRATION_TRUST_FILE`:
`{"providers":{"audit":{"key_hex":"<private-64-hex-key>","kinds":["quiescence","effect","endpoint_change","application_start","state_transfer","delivery"],"fixture":false}}}`.
Подписанный envelope содержит provider/payload/signature. Signature — HMAC-SHA256
канонического sorted compact ASCII JSON payload на независимом ключе. Общие
поля payload: version 1, kind, operation_id, digest, source_fingerprint,
target_fingerprint, token_fingerprint, observed_at. Quiescence также требует
no_writers=true, endpoint/start — endpoint_fingerprint. Provider проверяет
внешние факты до подписи. По умолчанию доверенных providers нет; fixture
providers не могут подтверждать реальные операции.
Из диагностики helper передавайте только `public-manifest.json`. Не архивируйте private dossier целиком; ошибка очистки требует закрытой сверки состояния.
Диагностика gateway использует фиксированные записи status/timing access log. Ошибки запросов nginx отбрасываются; внешний proxy проверяется отдельно.
Приёмка native privacy требует точного собственного build/digest, source-linked driver и проверки бинарника. Policy issue17-v1 заменяет текст native logs фиксированными severity до file/memory storage. Source driver не доказывает сквозную доставку webhook.

### Гейты точного кандидата #17

Запускайте `python3 tools/issue17_security_gate.py --unit` в чистом checkout
закоммиченного кандидата. `--runtime` проверяет disposable Compose/entrypoint/
gateway, а `--image botapi-candidate:check --expected-build-key BUILD_KEY` — точный
native image. Image workflow повторно квалифицирует существующие immutable tags
перед promotion. Отсутствие policy label, driver, положительного HTTP/log control
или обязательного runner блокирует успех. Публикуются только sanitized manifests.
Права Linux, полный discovery чистого кандидата, Docker/native image и Pages —
отдельные проверки. Недоступный локальный запуск: NOTRUN, verification deferred
to CI/gates. Synthetic tests не развёртывают сервис и не используют реального
Telegram-бота. Внешнее развёртывание требует отдельного разрешения.
