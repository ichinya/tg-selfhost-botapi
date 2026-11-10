---
title: Обслуживание
translation: /docs/en/maintenance.html
---

# Обслуживание

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

Workflow проверяет официальный исходник tdlib и digest Alpine 3.22 каждую ночь
около **04:37 Asia/Yekaterinburg** (23:37 UTC), при изменении основной ветки и
вручную. GitHub может задерживать запуск по расписанию.

Ключ сборки учитывает ревизии/digest, рецепт, entrypoint, патч, dependency policy,
инструменты сбора/валидации и проверки образа. Существующая сборка скачивается по
digest и снова проверяется перед reuse. Неоднозначный ответ registry останавливает
запуск; только подтверждённое отсутствие разрешает новую компиляцию.

Для нового образа workflow:

1. Проверяет применимость патча User-Agent к выбранной официальной ревизии.
2. Компилирует весь сервер.
3. Выполняет `--version`, проверяет строку заголовка в бинарнике и синтаксис entrypoint.
4. Проверяет package/compile evidence и warm-cache gate, сохраняет артефакты,
   затем публикует и сверяет уникальный candidate digest до назначения
   `ghcr.io/ichinya/tg-selfhost-botapi:build-<key>` и продвижения `latest`.

Ошибка проверки оставляет прежний опубликованный `latest`. Из PR публикации нет.
Наличие строки в бинарнике не заменяет проверку доставки реального webhook.

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
python3 tools/image_inputs.py --json-out .build-inputs.json --build-env-out .env.build
docker compose --env-file .env --env-file .env.build -f docker-compose.yml -f docker-compose.build.yml stop botapi
# До замены бинарника сохраните ./data и приватную конфигурацию.
docker compose --env-file .env --env-file .env.build -f docker-compose.yml -f docker-compose.build.yml build botapi
docker compose --env-file .env --env-file .env.build -f docker-compose.yml -f docker-compose.build.yml up -d --no-deps botapi
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
  --env-file /private/installation.env --env-file /private/stack/.env.build --project-directory /private/stack \
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

Image/default upstream logger qualification, multipart через shipped nginx, C++ sender harness, Jekyll rendered checks и реальная Telegram delivery остаются явными внешними гейтами. Недоступный запуск — NOTRUN: verification deferred to CI/gates. Изменение не заявляет всеобщую upstream debug/VLOG redaction (#17); сохраняйте низкую verbosity и отдельно квалифицируйте default logs перед deployment.

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


### Идентичность обновления APK

Resolver входных данных использует суточное UTC-окно обновления apk и поколение
из `tools/apk_policy.json`. Для срочного обновления в те же сутки увеличьте
поколение коммитом; уменьшать его нельзя. Это идентификатор сборки, а не снимок
пакетов и не доказательство воспроизводимости. Окно меняется в 00:00 UTC и
фиксируется один раз; переход через полночь во время компиляции не меняет inputs.

### Стадии установки APK

Оба независимых target `build-deps` и `runtime-deps` требуют `APK_REFRESH_ID`
перед installation RUN. Сначала обновляются все установленные пакеты, затем
устанавливаются зависимости из stable-ветки Alpine 3.22 с проверкой подписей.
`apk --no-cache` не отключает Docker layer cache: refresh-аргумент инвалидирует
обе установки. Исходная база пакетов, world, repositories, версия apk,
архитектура, версия Alpine и refresh ID сохраняются в final image под
`/usr/share/tg-selfhost-botapi/build/` и `runtime/`.


### Доказательства состава бинарника

Build evidence сохраняет фактические source/submodule revisions, версии compiler,
CMake/linker и Release-настройки, команду и map финальной линковки, SHA256 до strip
и установленного бинарника после strip, ELF NEEDED, hashes и package ownership
static inputs и разрешённых dynamic libraries. Python/binutils нужны только builder.
Извлечение и проверка без credentials:
`python3 tools/image_metadata.py --image IMAGE --inputs inputs.json --output receipt.json`.
Отсутствующие evidence, другой бинарник, refresh mismatch или неизвестный owner
использованного архива блокируют qualification. Внешний receipt связывает inventories
с config образа; внутренний compile record не включает собственный hash или digest.


### Qualification и повторное использование кандидата

CI разрешает один замороженный JSON-снимок. Ошибки авторизации/сети registry
останавливают запуск; сборка выбирается только при подтверждённом отсутствии
manifest. Reuse получает image по digest и повторяет metadata validation и smoke
(`--version`, строка заголовка, shell syntax entrypoint). PR собирается локально
без registry writes. Unit, Compose, metadata, smoke и отдельная cache regression
должны иметь PASS до публикации. Build tag нельзя заменить другим содержимым.
Уникальный candidate публикуется без повторной компиляции; проверяются registry
config, загрузка артефактов и продвижение latest по digest с readback.
Изменение default branch и более новый refresh latest блокируют старый rerun.
Переход UTC-полуночи сохраняет замороженные inputs. Artifacts хранятся 30 дней,
evidence внутри образа — весь срок хранения digest. Старые образы без evidence
требуют нового окна/generation.


### Подготовка каждой локальной пересборки

Генерируйте `.env.build` и `.build-inputs.json` resolver-ом непосредственно перед
каждой локальной сборкой; передавайте оба env-файла, как показано выше.
`up --build` не обновляет файл. Для внеочередного обновления увеличьте `generation`
в `tools/apk_policy.json`, закоммитьте и снова выполните resolver. Config/doctor
не запускают сетевое разрешение inputs.


### Подписанная regression с тёплым cache

CI явно запускает `tools/check_apk_refresh.py` с frozen inputs; unit discovery
никогда не вызывает Docker. Восстановленный runner использует изолированную
копию Dockerfile (документированный fallback): production upgrade/add/capture RUN
не меняются, перед refresh устанавливается подписанный synthetic v1 package.
URL repository, source/base и bytes context фиксированы. A/A доказывает cache hit
обеих установок; после появления v2 контроль со старым ID сохраняет v1, а новое
generation обновляет обе ветки. Dynamic и пересобранный static consumer должны
вернуть v2. Отдельные negative variants убирают refresh каждой установки и должны
выявить устаревшие evidence. Собственный builder ограничен 2 CPU/3 GiB и удаляет
только свои ресурсы. Cache purge/bypass не применяется. Logs, версии inventory,
hashes и receipts доказывают synthetic regression, а не статус CVE или VPS.


### Воспроизводимость и разбор scanner findings

Mutable stable repositories могут измениться внутри одних UTC-суток. Build key
обозначает выбранные inputs и refresh policy, registry digest — фактический образ.
Совпадение ключа не гарантирует побайтовой воспроизводимости. Ошибка или задержка
schedule откладывает обновление: исправление за 24 часа не гарантируется. Gateway
`nginx:alpine` имеет независимую dependency policy; этот срез не подтверждает весь
stack и не меняет совместимость состояния.

Каждую находку scanner разбирайте по точному digest, package name/version/Alpine
revision/architecture, advisory/backport status, фактической static/dynamic linkage,
версии scanner и timestamp его базы. Фиксируйте affected, fixed, not-applicable
или UNKNOWN со ссылкой на evidence. Одного runtime package scan недостаточно
для исключения статически включённой уязвимости. Применимая подтверждённая находка
требует update/rebuild и всех gates либо явно обоснованного исключения; неразобранная
находка остаётся unresolved и блокирует promotion. Без scan статус NOTRUN;
отсутствие вывода не считается clean scan. Универсальный scanner в #23 не вводится.

При missing legacy evidence или коллизии build tag увеличьте generation и разрешите
новый snapshot. Не перезаписывайте существующий build tag. UNKNOWN latest readback
требует проверки registry; автоматический rollback не заявляется. Registry publication,
synthetic regression, actual-image smoke и production — разные результаты.
Dependency refresh не требует миграции бота или token-bearing вызовов.

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
print("Source:", source.endpoint, "Target:", endpoint, "Token:", TOKEN, "Direction:", direction, flush=True)
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
