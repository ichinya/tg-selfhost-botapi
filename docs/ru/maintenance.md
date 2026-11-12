---
title: Обслуживание
translation: /docs/en/maintenance.html
---

# Обслуживание

Перед первым включением split storage создайте новый пустой host-каталог командой
`sudo install -d -m 0770 -o 101 -g 101 ./media`: Compose отказывает при отсутствии
root. Не применяйте эту команду рекурсивно к существующему cache.

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
Если соответствующий образ уже опубликован, компиляция пропускается.
Если проверка registry не подтвердила наличие образа, выполняется новая сборка.

Для нового образа workflow:

1. Проверяет применимость патча User-Agent к выбранной официальной ревизии.
2. Компилирует весь сервер.
3. Выполняет `--version`, проверяет строку заголовка в бинарнике и синтаксис entrypoint.
4. Собирает downloads, проверяет точную пару через synthetic local/TLS/security
   matrix и actual startup без сети, сохраняет IDs/source hashes и проверяет Pages.
5. Публикует проверенные Bot API/downloads `build-<key>` и продвигает их `latest`
   без пересборки.

Ошибка проверки оставляет прежний опубликованный `latest`. Из PR публикации нет.
Наличие строки в бинарнике не заменяет проверку доставки реального webhook.

Для расписания и публикации workflow должен быть в основной ветке. Запись в GHCR
использует `GITHUB_TOKEN` с `packages: write`. После первого выпуска настройте
публичность пакета либо авторизацию клиентов.

## Обновление установки

### Включение split storage и откат

1. Остановите клиентов, downloads, writers Bot API и supervisors, которые их
   перезапускают. Согласованно сохраните private state, identity образа, Compose/env,
   secret files и отдельно media для уже разделённой установки.
2. В окно обслуживания включите `docker-compose.files.yml` с проверенным образом
   и конфигурацией. Не копируйте state/binlogs в media и не исправляйте пути TDLib
   DB вручную. По умолчанию переход создаёт новый media cache.
3. Повторите getFile по сохранённым file_id. Перед доступом consumers проверьте
   новую media subtree, bytes/digest, ownership и mapping. Если upstream вернул
   старый private path, оставьте отказ и разберитесь в причине; доступ к state
   расширять нельзя. Сохранность старого cache/path не обещается. Холодный перенос
   с сохранением путей требует отдельной проверки выбранной upstream-версии.
4. Для rollback остановите новых writers и восстановите совместимые image,
   конфигурацию, private state и прежний layout из согласованного backup. Одного
   отката образа недостаточно. При self-to-self снимки media и state согласуются.

Не меняйте права cache рекурсивно и не открывайте его всем. Проверьте реальные
TDLib modes и UID/GID 101:101; reader использует ту же identity либо отдельно
проверенную read/traverse ACL. Каждому reader/handler — одна RO subtree, без parent,
соседних ботов, private temp/log/secrets и nested mounts. Local API и writer
доверенные; взаимно недоверенным операторам нужны отдельные instances/storage.

Для ротации замените защищённый Bearer-файл и перезапустите downloads. Проверьте
401 со старым credential и synthetic bytes с новым. Cache eviction, I/O timeout
30 секунд и общий deadline могут прервать передачу; Range/resume и retention SLA
не обещаются. Не вставляйте token-bearing paths в отчёты.

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
