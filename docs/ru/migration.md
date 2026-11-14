---
title: Миграция
translation: /docs/en/migration.html
---

# Миграция

Используйте полный reviewed checkout в Linux/WSL с Python 3.11+. Публичный [вход миграции](../../tg_selfhost_botapi_migrator.html) объясняет запуск same-origin loopback helper и не принимает секретов. Bash-вход — `migrate_off_to_self.sh`; sequencing, приватным state и recovery управляет Python. Отдельно скачанный shell отказывает до сети.

## Приватные входы и authority

Создайте каталог оператора вне checkout, Bot API state/media/temp и webroot. Режим каталога — 0700; token, profile, helper config, bootstrap и provider config — 0600. Секреты передаются содержимым файлов или environment, без positional arguments. Неявный dotenv из cwd не исполняется. Явный `--env-file` читается как данные; expansion и duplicate keys отклоняются. Приоритет: CLI > process environment > выбранный файл.

```sh
export MIGRATION_STATE_DIR=/private/migration-state
export BOT_TOKEN_FILE=/private/bot-token
export OLD_BOT_URL=https://api.telegram.org
export SELF_BOT_URL=http://127.0.0.1:18080
export MIGRATION_ACTION=polling
export MIGRATION_EVIDENCE_FILE=/private/deployment.json
export MIGRATION_TRUST_FILE=/private/trust.json
python3 tools/migration_cli.py plan --operation example
python3 tools/migration_cli.py status --operation example
python3 tools/migration_cli.py export --operation example
```

Plan резервирует operation и проверяет token-free infrastructure readiness. Без подписанного quiescence receipt исходный бот не опрашивается. Проверьте digest результата, затем получите свежий независимый quiescence receipt и явно примените план:

```sh
python3 tools/migration_cli.py apply --operation example --confirm-digest "$REVIEWED_DIGEST" --quiescence-file /private/quiescence.json
python3 tools/migration_cli.py status --operation example
python3 tools/migration_cli.py resume --operation example --quiescence-file /private/quiescence.json --endpoint-change-file /private/endpoint.json --application-start-file /private/start.json
```

Endpoint/start receipts получают после соответствующих checkpoints, без предварительной подписи. Для local-to-local передайте `--state-transfer-file` после confirmed close и остановленного переноса. Изменённые входы требуют новый plan; явно supersede можно только untouched plan. Status/export работают offline с сохранённым state; `status --refresh` — явный phase-aware сетевой запрос.

## Направления и actions

| Направление | Обязательный порядок |
| --- | --- |
| cloud_to_local | target readiness; quiesce/snapshot; source deleteWebhook(false), logOut; target authorization/configuration; endpoint change; controlled start |
| local_to_local | deleteWebhook(false), close; receipt остановленного переноса bot subtree; target authorization/configuration; endpoint/start |
| local_to_cloud | queue limitation acknowledgement, cloud target и cooldown evidence; detach, затем target после not-before |
| webhook_only | одинаковые source/target; только configuration/readback; без detach/state transfer |

Выберите `--direction` явно. local_to_cloud требует `--target-local-mode false --queue-limitation-ack`; cooldown подтверждается независимо. close/logOut могут отказать из-за upstream timing rules. Перенос per-bot state отличается от media mapping; общие binlogs нельзя копировать в другой активный сервер. Оба безопасных файловых контракта сохраняются, см. [конфигурацию](configuration.html).

Actions: preserve, set, polling. Пустой URL не выбирает polling. set требует URL; polling выполняет target deleteWebhook и проверяет пустой URL. Drop по умолчанию false; source delete всегда false. Явный drop относится только к target_configure и не повторяется вслепую после UNKNOWN. Full и URL-only profiles имеют разные гарантии.

## Helper

Приватный helper JSON содержит state_dir, allowed_endpoints, evidence_file, trust_file и fixture=false; optional forbidden_state_roots исключает local mount/webroot paths. evidence_file использует существующую deployment schema и обновляется доверенным оператором. Provider keys задаются независимо от journal binding key.

```sh
python3 tools/migration_helper.py --config /private/helper.json --bootstrap-file /private/bootstrap.txt
```

Откройте выведенный http://127.0.0.1 loopback origin и введите одноразовый bootstrap code из приватного файла. Host/Origin/session/CSRF проверки обязательны; Pages не обращается к loopback, wildcard CORS отсутствует. В browser session storage сохраняются только operation/digest. После потери ответа или reload прочитайте status существующей operation. Service readiness, migration, configuration и delivery показываются отдельно.

## Ошибки и bounded transport

Canonical stdlib Client использует по умолчанию 5s connect, 10s read, 20s total и ограничивает body. Redirects, proxy inheritance и automatic retries отключены. Typed HTTP/API/retry metadata сохраняется без raw descriptions. Подтверждённый 429 даёт WAITING/not_before (exit 3); неоднозначная мутация — UNKNOWN/BLOCKED. Intent записывается durable до send. Resume не повторяет неизвестные logOut/close/drop по прошедшему времени или пустому webhook. Нужен независимый server/transport audit. Delivery подтверждается отдельным trusted receiver/consumer receipt после controlled start.

Исторические raw-curl diagnostics в logs/migration — неподтверждённые legacy inputs (intent.json, receipt.json, summary.json, transport-error.txt). Они не импортируются как успешный engine state. Они остаются приватными и исключены из Pages. Raw retention исторических tools требует ограниченной приватной политики; generated Bash теперь ссылается только на canonical operations. Прежние MIGRATION_CONNECT_TIMEOUT/MIGRATION_REQUEST_DEADLINE (1..60 / 1..300) относятся к выведенному raw-curl path, а не к настройкам engine.

### Экспорт sealed plan
Экспорт использует существующие operation, digest и `MIGRATION_STATE_DIR`; отдельный curl-протокол не создаётся. Изменение входов требует нового plan. Секреты передаются приватно; содержимое token и certificate в экспорт не копируется. Legacy browser execution в этом выпуске заменяется входом в helper.

### Явный полный профиль webhook
Выбирайте preserve/set/polling явно. Приватный full profile содержит все поля: mode, url, secret_token, certificate_pem, ip_address, allowed_updates, max_connections. JSON null означает намеренное отсутствие secret/certificate/закреплённого IP; пропущенное поле означает unknown и отклоняется. Пустой список updates и явный connection limit — отдельные решения. Certificate отправляется multipart InputFile. URL-only имеет ограниченный scope.
Full preserve дополнительно требует свежий подписанный quiescence receipt независимого аудитора конфигурации с original_config_verified=true и точным profile_fingerprint плана. Readback не подтверждает прежний secret. Без такого аудита full preserve блокируется до detach; используется существующая граница trusted provider. Readback конфигурации и доставка secret/header учитываются отдельно.

### Восстановление и authority
Приватный journal хранится вне state/media/webroot. Canonical engine резервирует operation бота до bot-bearing observations, пишет intent до мутации и сохраняет UNKNOWN при неоднозначном transport outcome. Resume не повторяет неизвестные logOut/close/drop. Нужен независимый audit receipt; прошедшее время и пустой webhook недостаточны. Авторизация target ждёт подтверждённого detach, а для local-to-local — проверенного переноса остановленного bot subtree. Readiness, migration, configuration и delivery остаются отдельными результатами. Чтение private evidence отклоняет special files и concurrent replacement.

### Bash-вход и legacy recovery
Используйте полный проверенный checkout с Python 3.11+ в Linux/WSL. `bash migrate_off_to_self.sh plan|apply|status|resume|reconcile|export` делегирует tools/migration_cli.py. Нужны явные `--operation`, MIGRATION_STATE_DIR и action; прежние aliases SELF_BOT_URL/TELEGRAM_BOT_URL и WEBHOOK_URL/WEB_HOOK читаются как данные. Неоднозначные positional tokens отклоняются до сети. Отдельно скачанный shell прекращает работу до выполнения операций, если runtime dependencies отсутствуют.

Для необязательного мониторинга создайте в checkout каталог `.observability/migration` с владельцем-оператором и правами 0755, задайте его абсолютный путь в `MIGRATION_STATUS_DIR` и публичный псевдоним в `MIGRATION_STATUS_ALIAS`. CLI атомарно публикует очищенную проекцию сохранённого журнала текущей операции. Polling разрешает только подтверждённое состояние миграции; plan и неизвестное состояние его не разрешают. Ошибка публикации сообщается в stderr и не меняет код выхода миграции. Файл отражает одну операцию: для независимо управляемых операций используйте отдельные checkout и каталог мониторинга.
Старые journals wp_migration_main — неподтверждённый исторический вход. Остановите writers приложения, независимо проверьте последний подтверждённый effect и выполните ручную сверку до нового plan; не повторяйте logOut для выяснения результата.

### Публичный URL мигратора
Прежний tg_selfhost_botapi_migrator.html — статический двуязычный вход. Он не принимает токены и не вызывает Bot API/localhost. Запустите helper из того же checkout и отдельно откройте его loopback URL. Helper отдаёт UI четырёх направлений и трёх actions на одном origin с приватным bootstrap, session и CSRF. При потере ответа сначала прочитайте status той же operation. Изменение формы сбрасывает подтверждение digest. Совместимость URL не сохраняет legacy standalone execution.

### Ограниченные Compose checkpoints
`python3 tools/migration_compose_provider.py --config /private/provider.json --state-dir /private/migration-state --operation example --kind quiescence` читает только явно разрешённые полные container IDs. Приватная конфигурация задаёт provider/key_hex, fixture, project, containers (service/image IDs), application, endpoint, endpoint_variable и target_fingerprint. Тот же независимый ключ задаётся в TrustedReceipts для разрешённых kinds. Получайте receipt на соответствующем этапе, не подписывайте заранее весь перенос. Endpoint change требует остановленное приложение с совпадающим effective environment; controlled start сверяет время generation с target verification и endpoint change.
Allowlist должен содержать всех writers. Collector не обнаруживает неизвестных внешних writers, не подтверждает прежний secret, потерянный logOut/close, перенос state или доставку. Эти границы остаются BLOCKED без независимых аудиторов. Docker socket нельзя монтировать в browser, gateway или helper.

### Итоговый статус приёмки
Shipped root entry и regenerated adapters используют canonical authority. CI/POSIX, image, native ARM64, browser/rendered-site, full upload, cold restore, VPS и реальная Telegram delivery в этом проходе NOTRUN. С каждым будущим receipt сохраняйте operation/digest и exact image identities. Эти offline checks не переносили и не проверяли существующих production ботов.

Исторические labels CONFIRMED_REJECTION и NOT_SENT относятся к выведенной raw-curl projection. Canonical engine сохраняет typed failed/waiting/unknown outcomes. getWebhookInfo подтверждает наблюдаемые поля, но не возвращает secret_token.
