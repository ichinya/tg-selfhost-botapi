---
title: Миграция
translation: /docs/en/migration.html
---

# Миграция

Прежний HTML URL загружает один ES-модуль и работает через локальный helper.
Прямых Bot API и произвольных webhook HEAD запросов нет. После refresh браузер
восстанавливает только ID/digest и читает status. Изменение полей создаёт новый
draft; поздний ответ прежней формы его не заменяет. Потеря apply response означает
неизвестность для UI: читайте durable status той же операции.

## Контракт исполнителя

Контракт миграции версии 2 использует неизменяемые ID и digest операции,
ключевые привязки endpoint/токена/профиля и единственный drop на целевой стороне.
Планы версии 1 отвергаются. Секреты и URL подаются отдельно и не входят в
публичный план. Подтверждённый шаг остаётся историческим свидетельством;
потерянный ответ означает UNKNOWN до допустимой сверки по доказательствам.

Общий реестр описывает Cloud → Local (удаление без drop, logOut, авторизация,
настройка), Local → Local (удаление, close, внешний перенос состояния,
авторизация, настройка), Local → Cloud (удаление, logOut, cooldown,
авторизация, настройка) и Webhook only (настройка). Зависимости требуют
подтверждения. Local → Cloud требует принятия ограничения непрерывности
очереди. Полный типизированный профиль и явная область `url_only`/polling
привязаны к неизменяемому плану.

Исполнитель резервирует операцию до наблюдений source. Target не получает
токен до подтверждённого detach, а в Local → Local — до проверенного receipt
внешнего переноса. Сохраняйте backup source; receipt связывает совпадающие
manifest commitments, close attempt, deployments, UID/GID/layout и отсутствие
writers. Без доверенного provider checkpoint остаётся BLOCKED.
`close` с 429 означает WAITING с `not_before`, без автоматического цикла retry.
Cloud cooldown — явный вход с подтверждением. Отказ target после detach даёт
PARTIAL. Readiness, миграция, webhook и доставка имеют отдельные итоги;
доставка изначально NOTRUN. Полный preserve без проверки исходных приватных
настроек блокируется до detach.

`status` работает offline. `status --refresh` и `resume` сверяют только
наблюдения, допустимые в текущей фазе. UNKNOWN logOut/close не вызывает запросов
с токеном ни к одной стороне. UNKNOWN drop и скрытые secret/certificate требуют
независимых свидетельств. Реальные checkpoints/effects/delivery принимают receipts
с подписью явно настроенного независимого audit provider; JSON-полей или галочки
оператора недостаточно. Поставляется HMAC-контракт provider, а не специфичный
сборщик аудита платформы. Fixture trust допустим только для fixture-операций.
Исторические подтверждения сохраняются при drift.

## Общий CLI и экспорт

Используйте Python 3.11+ в Linux/WSL. Задайте `BOT_TOKEN` либо `BOT_TOKEN_FILE`,
явные `OLD_BOT_URL`, `SELF_BOT_URL`, `MIGRATION_ACTION` и private deployment evidence.
Пустой webhook не выбирает polling/preserve. Приоритет: CLI, process environment,
явный `--env-file`. Env читается как данные с allowlist, shell expansion запрещён.
Старое имя Bash сохраняется и передаёт субкоманды общему CLI. Позиционные
token/target/webhook отклоняются без вывода значений; используйте environment
или явно выбранный приватный файл ввода. Legacy-вызов выводит sealed plan;
для выполнения нужен отдельный apply с его digest. Старой curl-последовательности нет.

```sh
python3 tools/migration_cli.py plan --operation move-01 --action polling
python3 tools/migration_cli.py status --operation move-01
python3 tools/migration_cli.py apply --operation move-01 --confirm-digest PLAN_DIGEST --quiescence-file "$QUIESCENCE_FILE"
python3 tools/migration_cli.py resume --operation move-01 --endpoint-change-file "$ENDPOINT_RECEIPT" --application-start-file "$START_RECEIPT"
python3 tools/migration_cli.py export --operation move-01
```

Коды: 0 — запрос обработан (смотрите outcome), 1 — доказанный отказ шага,
2 — UNKNOWN/BLOCKED/нужен checkpoint, 3 — WAITING, 4 — input/state error.
Экспорт сохраняет ID/digest и ссылается на `MIGRATION_STATE_DIR`, новую authority
не создаёт. Профиль/сертификат подавайте через приватный `--profile-file`.

При переносе меняется Bot API endpoint приложения и, при необходимости, webhook.
До начала нужно знать старый endpoint. Облачный `getMe` не подходит для нейтрального
определения текущего сервера: запросы с токеном могут влиять на сессию.

Остановите приложение или фоновый процесс, который обращается к старому API.
Подготовьте новый сервис без авторизации этого бота, сохраните состояние и профиль
webhook. `getWebhookInfo` не возвращает прежний `secret_token`; храните его в своей
конфигурации.

## Выбор сценария

| Сценарий | Подход |
| --- | --- |
| Тот же Bot API, другой webhook | Изменить webhook и проверить фактический результат; сервер не переносится |
| Облако Telegram → локальный | Выполнить облачный `logOut` до обращения к локальному API |
| Локальный → локальный | Следовать официальной процедуре с переносом состояния, описанной ниже |
| Локальный → облако | Выйти из старого локального сервера перед переключением; учесть очередь и доступность облака |

Основной источник — [README официального сервера](https://github.com/tdlib/telegram-bot-api#moving-a-bot-to-a-local-server).
Также см. методы [logOut](https://core.telegram.org/bots/api#logout) и
[close](https://core.telegram.org/bots/api#close). После выхода из облака немедленное
возвращение в него ограничено правилом Telegram о десяти минутах.

### Облако → локальный сервер

1. Проверьте доступность и настройки целевой инфраструктуры.
2. Остановите приложение, использующее облачный endpoint.
3. Сохраните профиль webhook и выберите поведение для накопившихся обновлений.
4. Вызовите `logOut` в облаке, затем измените Bot API endpoint приложения.
5. Установите полный профиль webhook на новом сервере либо явно выберите polling.
6. Проверьте фактические настройки, ошибки доставки и тестовое обновление, затем возобновите работу.

### Локальный → локальный с переносом состояния

Официальная процедура сохранения обновлений: `deleteWebhook`, затем `close` на
старом сервере, после чего перенос подкаталога бота (по его user ID) в рабочий
каталог нового сервера. После переноса продолжайте запросы на новом сервере.
Если `close` вернул `retry_after`, обработайте ожидание до следующих действий.

Нужны согласованная резервная копия, сохранение владельца и путей, а также запрет
одновременной работы с одним состоянием. Одно лишь `drop_pending_updates=false`
не переносит данные и не гарантирует непрерывность.

## Совместимость адаптера

Используйте `bash migrate_off_to_self.sh plan/apply/status/resume/export ...`
с теми же флагами, что Python. Для самой миграции curl/jq не нужны.
Файлы `.env` и `.env.example` репозитория предназначены только для Compose.
Параметры миграции передавайте через environment или отдельный приватный файл
с явным `--env-file`; wrapper автоматически `.env` не читает.
Environment имеет приоритет. Пустой webhook требует явного action и в legacy-mode.
Используйте `BOT_TOKEN` или `BOT_TOKEN_FILE`; позиционные credentials отклоняются.
Legacy-mode выводит plan и возвращает
код 2 для отдельного подтверждения digest; автоматического apply нет.

## Работа в браузере

[Прежний URL мигратора](../../tg_selfhost_botapi_migrator.html) на Pages показывает
входной экран. [Запустите helper](getting-started.md#локальный-ui-миграции), введите
код из приватного pairing-файла, выберите direction/action/mode и нажмите Plan. Проверьте
ID/digest, scope профиля, drop и порядок шагов. Реальная подготовка может
создать sealed plan без наблюдений source; apply требует свежей подписанной
quiescence. Введите проверенный digest и необходимые provider receipts.
После timeout используйте Status той же операции, затем Resume. Refresh — явное
online-действие; обновление вкладки автоматически читает только сохранённый status.

Helper рассчитан на одного оператора и один хост. UI, CLI и export используют
общую private authority; независимые state roots не входят в эту гарантию.
Native Windows/state на Windows-дисках WSL не поддерживаются. Docker diagnostics
явно выполняют write probes. Unmanaged deployment evidence — аттестация оператора
с TTL, а не автоматическая проверка.

## Свидетельства и ограничения

Local → Cloud использует token-free readiness официального cloud вместо local
image/mount evidence. Нужны известный `--cloud-not-before` и
`--queue-limitation-ack`; подписанная quiescence также подтверждает
`cloud_not_before`, `cloud_availability_verified: true`, `queue_limitation_ack: true`.
Неизвестный cooldown блокирует авторизацию. Истечение десяти минут не доказывает
detach, ответ которого потерян.

Typed `full` profile поддерживает URL, secret_token, certificate_pem,
allowed_updates, max_connections и ip_address. Храните его в private JSON.
Успешная настройка и наблюдаемые поля не доказывают доставку или будущую
актуальность secret/certificate. Полный preserve без независимой проверки
исходного профиля остаётся BLOCKED; явный full set поддерживается. URL-only
требует согласия. Source delete всегда использует drop=false. Явный target drop
имеет durable attempt и после потери ответа не выводится из pending_update_count.
Exactly-once и непрерывность очереди через удалённый API не обещаются.

Для сохранения polling источника явно выберите action `preserve` с приватным
профилем `{"mode":"polling"}` (в UI есть соответствующая область профиля).
После detach исполнитель удалит старый webhook на target и проверит пустой URL.
Webhook-only preserve — проверяемый no-op; сочетание с drop отклоняется до API.
Матрица приёмки проверяет двенадцать сочетаний направления и действия и четыре
варианта сохранения polling на настоящих HTTP mocks с loopback-адресами.

См. [восстановление](maintenance.md#восстановление-журнала-миграции),
[private configuration](configuration.md#приватное-состояние-миграции) и
[изолированный mock walkthrough](maintenance.md#isolated-mock-walkthrough).

[Настройки](configuration.md) · [Обслуживание](maintenance.md)

## Предварительная диагностика миграции doctor

Запуск: `python3 tools/doctor.py --scenario official-to-self --migration-input /private/decisions.json`.
Строгий контракт входа — `tools/doctor-input.schema.json`. Храните реальный файл
вне любого Git checkout и webroot с правами только владельца на POSIX. В нём
только решения по подготовке: без токенов, URL, API hash и содержимого сертификатов.
Гарантии приватности файла на native Windows остаются UNKNOWN.

Вход v1 начинается с `schema_version: 1`. Задайте
`delivery_action: preserve|set|polling`, явный boolean `drop_pending_updates`
(в том числе false), `file_access: not_used|local_path|shared_volume|remote_authenticated`
и boolean `workflow_prepared`. Декларация workflow включает остановку приложения
на нужном этапе, backup, переключение endpoint и обработку абсолютных путей при
использовании файлов. Для preserve/set добавьте `webhook_profile_prepared`:
полный профиль, обработка secret/certificate, IP, connections и allowed updates
должны быть подготовлены в отдельной защищённой конфигурации. Секрет webhook
и полный URL во вход doctor не входят.

```json
{
  "schema_version": 1,
  "delivery_action": "polling",
  "drop_pending_updates": false,
  "file_access": "not_used",
  "workflow_prepared": true
}
```

Пример декларирует подготовленный план, а не уже выполненные действия.
`remote_authenticated` остаётся UNKNOWN без независимой проверки безопасного
контракта на границе #5; doctor v1 не реализует download service.
Local/shared file access остаётся UNKNOWN до независимой проверки путей/volumes
приложения: выбор режима не доказывает наличие mapping.

Для `self-to-self` отдельно выберите source через `--source-file`,
`--source-env-file`, `--source-profile`, `--source-project-directory` и
`--source-project-name`. Добавьте `transfer` с явным `method`, boolean
`backup_prepared` и `exclusive_use_plan_prepared`, а также `backlog_policy`:
`drain` или `accept-loss`. State backings должны различаться.

- `per-bot` требует `state_subdir`: один относительный компонент каталога внутри
  source work root. Измеряется только это поддерево; shared tqueue/webhook stores
  с ним не переносятся, поэтому политика backlog должна учитывать их отдельно.
  Поддерево назначения должно отсутствовать.
- `dedicated-cold` измеряет весь work root вместе с shared stores. Нужны также
  `dedicated_source: true` и `target_empty_prepared: true`. Backup охватывает весь
  source; план exclusive use останавливает всех writers и supervisors на границе
  копирования. Наблюдаемый корень назначения должен быть пустым.
- `fresh-login` требует `backlog_policy: accept-loss`; `state_subdir` не задаётся.
  Поддерево, copy capacity и совместимость копии получают необязательный SKIP;
  базовые проверки storage остаются обязательными.

Измеряются только метаданные. Их изменение, symlinks, вложенные mounts и
неподдерживаемые entries дают UNKNOWN. Hard links не удваивают измеренные bytes.
Резерв target включает измеренные bytes/entries плюс 10%; необязательные
`transfer_metadata` остаются декларацией и не подтверждают capacity.
Baseline совместимости — совпадающие наблюдаемые версии бинарника и доступные
source revisions; различающиеся или неизвестные версии дают UNKNOWN.

`self-to-official` также требует `source_backup_prepared: true` и
`source_backlog_policy: drain|accept-loss`; подготовленный workflow начинается
с logout. Проверяются локальный source и подготовка ручного workflow.
Cloud authorization, ограничения session и delivery остаются непроверенными.
`hook-only` даёт BLOCKED/1 с `unsupported_scenario` (#7/#9). Отсутствующие решения
дают UNKNOWN/3 с именем поля; false preparedness или небезопасные POSIX-права —
BLOCKED/1; неверный или нечитаемый вход — exit 2. Отчёт сохраняет pending actions и unverified facts.
Doctor не запускает миграцию, helpers, методы бота, cloud probes, journals и locks.
READY означает готовность начать подготовленную процедуру и не подтверждает
helpers, завершённый перенос, авторизацию или доставку.
