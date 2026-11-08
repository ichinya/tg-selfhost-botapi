---
title: Миграция
translation: /docs/en/migration.html
---

# Миграция

При переносе меняется Bot API endpoint приложения и, при необходимости, webhook.
До начала нужно знать старый endpoint. Облачный `getMe` не подходит для нейтрального
определения текущего сервера: запросы с токеном могут влиять на сессию.

Остановите приложение или фоновый процесс, который обращается к старому API.
Это включает pollers, фоновые задания, retries и supervisor. Webhook-приёмник —
отдельный процесс: остановка API-клиента не замораживает очередь и доставку Bot API.
Оставьте приёмник доступным, пока обрабатываются прежние обновления.
Подготовьте новый сервис без авторизации этого бота, сохраните состояние и профиль
webhook. `getWebhookInfo` не возвращает прежний `secret_token`; храните его в своей
конфигурации.

Локальный Bot API с `--local` допускает HTTP- и HTTPS-адреса webhook; официальный облачный Bot API требует HTTPS.

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

Утилита проверяет корень target без токена, с таймаутом и без перехода по redirects.
Характерный ответ 404 не подтверждает подлинность узла. До запросов с токеном
подтвердите source, target, webhook и политику сброса. Отключение webhook и
`logOut` на source должны успешно завершиться до первого target `getMe`.
Ошибка HTTP/API, некорректный ответ или неизвестный результат изменения
останавливают цепочку. Не проверяйте обе стороны входом и не повторяйте потерянный
`logOut` автоматически.

### Локальный → локальный с переносом состояния

Официальная процедура для отдельного бота: `deleteWebhook` без намеренного сброса,
успешный `close` на старом сервере, затем перенос подкаталога бота (найденного по
user ID) в рабочий каталог совместимой цели. Сначала остановите старые API-клиенты.
Ошибка `close`, включая 429/`retry_after`, или неизвестный ответ запрещают перенос
и вход на target. Не повторяйте запрос вслепую. Имя каталога может содержать токен:
не публикуйте его в журналах.

В [закреплённом ClientManager.cpp](https://github.com/tdlib/telegram-bot-api/blob/e3e9dd8e5b3d7ab8537cd5a10dc31d5ffa8f82d1/telegram-bot-api/ClientManager.cpp)
есть важная граница хранения: `tqueue.binlog` и `webhooks_db.binlog` находятся в
общем рабочем каталоге, вне каталогов отдельных ботов. Перенос одного подкаталога
не доказывает сохранность накопленной локальной очереди. На общем сервере сначала
обработайте backlog или явно учтите его потерю. Объединение shared binlogs с
действующим многоботным target не поддерживается. `drop_pending_updates=false`
не переносит данные и не гарантирует их сохранность. Простой выход через source
`logOut` и новый вход на target допустимы при принятой потере локального backlog.

Для **выделенной установки** предусмотрен отдельный cold-transfer:

1. Выберите окно обслуживания. Остановите все API-клиенты, retries и supervisor;
   сохраните полный профиль webhook и согласованную [резервную копию](maintenance.md).
2. Отключите source webhook без намеренного сброса и получите успешный `close`.
   Любая ошибка или неизвестный результат останавливают процедуру.
3. Остановите все source writers и контейнеры Bot API до копирования рабочего
   каталога. Не допускайте повторного запуска старого сервиса через `restart: always`
   или внешнюю автоматику. Остановка общего контейнера затронет всех его ботов.
4. Перенесите весь согласованный рабочий каталог, включая общие хранилища, только
   на пустую совместимую цель. Сохраните владельца и права; проверьте версии,
   mounts и обработку абсолютных путей медиа в приложении. Не копируйте живую БД
   и не перезаписывайте общие binlogs другой установки.
5. Отдельно проверьте перенос и отсутствие прежних writers. Только затем запустите
   target и выполните первый запрос с токеном (`getMe`).
6. Восстановите нужный профиль webhook либо явно настройте polling. Проверьте
   фактическую конфигурацию и тестовое обновление перед возобновлением трафика.

Браузер выдаёт для этого сценария отдельные ручные этапы. Он не копирует state
и не формирует единый исполняемый план, перескакивающий через перенос. Mock-тесты
не доказывают сохранность обновлений Telegram при реальном переносе.

### Локальный сервер → облако

Обработайте backlog или явно примите его потерю, остановите все старые API-клиенты,
сохраните профиль, отключите webhook и получите успешный локальный `logOut` до
любого облачного запроса. Локальный `logOut` может очистить очередь даже после
`deleteWebhook` с `drop_pending_updates=false`. Облако не импортирует локальный state.
После восстановления доступности cloud выполните облачный `getMe`, восстановите
профиль или явный polling и проверьте доставку. При ошибке или неизвестном исходе
остановитесь.

Этот logout-first рецепт — вывод из реализации upstream и общих правил переноса,
а не отдельная дословная инструкция upstream для local → cloud. Ограничение
возврата в cloud на десять минут после облачного `logOut` и окно 429 локального
`close` — разные ограничения. Браузер выдаёт ручной план, не исполняя этот переход.

## Bash-утилита

Текущий скрипт поддерживает переход **из облака на локальный сервер**. Он читает
`.env` рядом со скриптом либо файл `ENV_FILE` (относительный путь считается от
рабочего каталога вызова). Отсутствие файла по умолчанию допустимо; ошибка явно
указанного файла останавливает запуск. Файл исполняется как доверенный код Bash,
это не песочница. Приоритет: аргументы, окружение процесса, файл, значения по
умолчанию. В одном источнике `SELF_BOT_URL` и `WEBHOOK_URL` имеют приоритет над
старыми именами `TELEGRAM_BOT_URL` и `WEB_HOOK`; старое имя в окружении сильнее
значения из файла. Пустой webhook сохраняет прежнюю логику выбора, описанную
ниже. Из другого каталога можно вызвать `ENV_FILE="/path/to/settings.env" bash
/path/to/migrate_off_to_self.sh "$BOT_TOKEN"`.

Порядок аргументов: `BOT_TOKEN`, `SELF_BOT_URL`, затем `WEBHOOK_URL`:

<!-- issue10-example:environment -->
```sh
export WEBHOOK_SECRET_MODE=none WEBHOOK_IP_MODE=dns WEBHOOK_MAX_CONNECTIONS=40
set -euo pipefail
read -rsp 'Bot token: ' BOT_TOKEN; printf '\n'
SELF_BOT_URL="http://127.0.0.1:18080" \
WEBHOOK_URL="https://example.com/telegram/webhook" \
  bash ./migrate_off_to_self.sh "$BOT_TOKEN"
unset BOT_TOKEN
```

Можно передать все три аргумента позиционно. Webhook нельзя ставить вторым
аргументом: это место адреса Bot API.

<!-- issue10-example:positional -->
```sh
export WEBHOOK_SECRET_MODE=none WEBHOOK_IP_MODE=dns WEBHOOK_MAX_CONNECTIONS=40
set -euo pipefail
read -rsp 'Bot token: ' BOT_TOKEN; printf '\n'
bash ./migrate_off_to_self.sh "$BOT_TOKEN" \
  "http://127.0.0.1:18080" "https://example.com/telegram/webhook"
unset BOT_TOKEN
```

Обе формы используют внешний API-порт **18080**; nginx передаёт запросы на
`botapi:8081`. Webhook — адрес приложения. Команды не запускают polling consumer.
Из другого рабочего каталога используйте абсолютный путь к утилите:

```sh
read -rsp 'Bot token: ' BOT_TOKEN; printf '\n'
ENV_FILE="/path/to/settings.env" \
  bash /path/to/migrate_off_to_self.sh "$BOT_TOKEN"
unset BOT_TOKEN
```

`DROP_PENDING_UPDATES=true` удаляет накопившиеся обновления. По умолчанию — `false`.

### Текущие ограничения утилиты

- Проверка целевого сервера без токена распознаёт характерный ответ об ошибке,
  но не подтверждает подлинность узла или готовность бота. Проверьте адрес до согласия.
- Запросы с токеном начинаются после подтверждения. Продолжение после неизвестного
  результата `logOut` не реализовано; не перезапускайте перенос вслепую.
- Пустой аргумент webhook восстанавливает старый URL, если он был задан. Это не
  явный выбор polling.
- Helper и браузер разрешают полный желаемый профиль до изменения source.
  Прежний секрет и публичный сертификат задаются явно: WebhookInfo не раскрывает эти данные.
- Токены могут быть видны в аргументах процессов и журналах.

Исправления отслеживаются в [#2](https://github.com/ichinya/tg-selfhost-botapi/issues/2),
[#7](https://github.com/ichinya/tg-selfhost-botapi/issues/7) и
[#9](https://github.com/ichinya/tg-selfhost-botapi/issues/9).
Перед использованием с работающей установкой проверьте процедуру на тестовом боте.

## Браузерный инструмент

[Открыть мигратор](../../tg_selfhost_botapi_migrator.html). Это статическая страница,
а не серверный исполнитель миграции. Запросы идут из вашего браузера; API должен
разрешать соответствующий origin и доступ.

Локальные проверки и построение плана не отправляют запросов. Проверка состояния
требует согласия и читает только явно выбранный source, не определяя текущий
сервер бота. Cloud → local проверяет target без токена, запрашивает согласие,
читает source, отключает там webhook и выходит, затем обращается к target.
Webhook-only не вызывает `logOut` и `close`. Изменение формы сбрасывает прочитанное
состояние. Ошибка или неизвестный исход изменения блокирует дальнейшее выполнение
на странице до ручной сверки состояния. Локальные переходы выполняются по чеклистам.

В выполнении и генераторе плана остаются ограничения
[обработки ошибок](https://github.com/ichinya/tg-selfhost-botapi/issues/6) и
[shell-экранирования](https://github.com/ichinya/tg-selfhost-botapi/issues/8).
CORS-ошибка может скрыть ответ уже выполненного изменяющего запроса. Перед новым
планом выясните текущее состояние. Проверяйте команды перед выполнением.

## Polling, профиль webhook и файлы

Профиль webhook #7 интегрирован. Перенос state #5 и семантика действий #9 остаются
независимыми; их незавершённые модули не являются runtime dependencies. Пустой webhook
сохраняет legacy-наследование; это не действие polling. Для явного polling после
завершения перехода между серверами вручную удалите webhook на **target** и
проверьте, что `result.url` — строка, равная `""`:

```sh
# BOT_TOKEN и SELF_BOT_URL относятся к выбранному target после миграции.
set -euo pipefail
curl -q -fsS --connect-timeout 5 --max-time 30 -X POST \
  "$SELF_BOT_URL/bot$BOT_TOKEN/deleteWebhook" \
  --data-urlencode 'drop_pending_updates=false' | jq -e '.ok == true and .result == true'
curl -q -fsS --connect-timeout 5 --max-time 30 \
  "$SELF_BOT_URL/bot$BOT_TOKEN/getWebhookInfo" | \
  jq -e '.ok == true and (.result.url | type == "string") and .result.url == ""'
```

При ошибке любой проверки остановитесь. Собственный polling-клиент запускайте
после сверки; примеры не потребляют обновления. URL readback не доказывает доставку
webhook. Восстановите `secret_token`, сертификат, `allowed_updates`, `max_connections`
и остальные нужные настройки из сохранённого профиля. Секрет и загруженный
сертификат нельзя восстановить из `getWebhookInfo`.

В local-режиме абсолютный `getFile.file_path` обозначает путь сервера/контейнера.
Нужны совместимые mounts и пути приложения; перенос state сам по себе их не
исправляет. nginx передаёт запросы `/file/` в Bot API, не открывая каталог
состояния. Не приписывайте ему авторизацию `X-Telegram-Bot-Token`.
См. [доступ к файлам](configuration.md).
Порт 18081 отдельного downloads-сервиса не заменяет API-порт 18080.

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

## Полный профиль webhook

До изменения source helper разрешает `WEBHOOK_SECRET_MODE=provided|none`, `WEBHOOK_IP_MODE=dns|pinned`, `WEBHOOK_CERTIFICATE_MODE=provided|none`, `WEBHOOK_ALLOWED_UPDATES` (JSON-массив строк), `WEBHOOK_MAX_CONNECTIONS`, `WEBHOOK_TARGET_LOCAL=true|false`. Неизвестный секрет/IP и отсутствующий custom certificate останавливают preflight. `fixed` — алиас pinned для canonical IPv4. Source `ip_address` не раскрывает намерение pinning. Явные параметры перекрывают source; отсутствие optional updates означает документированный default `[]`. `[]` исключает chat_member, message_reaction и message_reaction_count, а не включает все типы. Null и неверные типы отклоняются. Per-bot max_connections: 1–100; до 100000 только при явном подтверждении local mode (`TELEGRAM_LOCAL`/`--local`), независимо от серверного `TELEGRAM_MAX_WEBHOOK_CONNECTIONS`. Self-host URL этого не доказывает.

Используйте ровно один из `WEBHOOK_SECRET_TOKEN` и `WEBHOOK_SECRET_TOKEN_FILE` для provided; none явно утверждает отсутствие секрета. В файле разрешён один конечный LF/CRLF; inline-секрет не обрезается. `WEBHOOK_CERTIFICATE_FILE` — публичный PEM, никогда private key. Protected files, включая `BOT_TOKEN_FILE`, должны находиться вне checkout/webroot с доступом только оператору. Process env перекрывает trusted `ENV_FILE` (по умолчанию `.env` рядом с helper), включая явные пустые значения; пары value/file выбираются на одном уровне. Positional URL имеют высший приоритет. Для polling профиль webhook не применяется.

Передача полного профиля включена: urlencoded без сертификата, полностью multipart с сертификатом. Секрет и scalar-файлы — приватные снимки; токен/секрет/URL не попадают в curl argv и raw diagnostics. Helper отключает trace, применяет curl -q без redirects, проверяет HTTP/ok/result и не повторяет мутации. Для публичного PEM нужны Bash 4+, jq, curl, realpath и проверка openssl X.509; private key отклоняется. Временные файлы создаются с umask 077 и очищаются при выходе/сигналах.

В автономном браузере добавлены secret/none, JSON updates, connections/local capability, DNS/fixed IPv4 и File публичного сертификата. Неполный профиль блокирует мутации. Файлы фиксируются до logout; загрузка использует FormData без ручного boundary. Изменения формы сбрасывают снимки, сохраняя UNKNOWN/completion locks. Переходы local→local/cloud остаются отдельными ручными этапами.

Экспорт/clipboard содержит standalone Bash runtime и ссылки на environment. Профиль, токен и URL задаются повторно через trusted runtime inputs; browser values, private paths и байты сертификата не экспортируются. Source читается заново при выполнении. Ручные переходы сохраняют STOP barrier и используют отдельный запуск helper с `MIGRATION_MODE=target-stage` после приёмки lifecycle/state. После UNKNOWN/completion доступно только руководство по сверке.

Postflight делает два чтения target через две секунды с общим deadline десять секунд. Сверяются точный URL, множество updates, connections, наличие сертификата и fixed IP. DNS IP — наблюдение. Тренд очереди и исторические/новые delivery/synchronization errors выводятся отдельно, только безопасными счётчиками. Пустая очередь не доказывает доставку. WebhookInfo не проверяет байты секрета и сертификата. Новые ошибки, отсутствующие счётчики или несовпадения останавливают приёмку; мутации не повторяются.

### Защищённый профиль и восстановление

Два прежних кратких примера явно выбирают none: используйте их только для receiver без прежнего секрета. Для защищённого receiver подготовьте файлы с доступом только оператору вне checkout/webroot и используйте этот пример с плейсхолдерами:

```sh
export BOT_TOKEN_FILE=/secure/bot-token
export SELF_BOT_URL=http://127.0.0.1:18080
export WEBHOOK_URL=https://example.com/telegram/webhook
export WEBHOOK_SECRET_MODE=provided
export WEBHOOK_SECRET_TOKEN_FILE=/secure/previous-webhook-secret
export WEBHOOK_IP_MODE=dns
export WEBHOOK_ALLOWED_UPDATES='["message","callback_query"]'
export WEBHOOK_MAX_CONNECTIONS=40
export WEBHOOK_CERTIFICATE_MODE=provided
export WEBHOOK_CERTIFICATE_FILE=/secure/public-certificate.pem
bash ./migrate_off_to_self.sh
```

Браузер использует password/File controls и не сохраняет private inputs в storage. Preflight браузера проверяет структуру PEM; сертификат проверяется target API при принятии. Helper дополнительно проверяет X.509 через openssl. Экспорт требует повторного ввода private inputs при запуске и не содержит browser token, secret, URL, байты сертификата или настоящее имя private file. Ручной план содержит безусловный STOP/exit перед отдельным сохраняемым target-stage script; перенос state он не выполняет. Для target-stage нужны явные сохранённые URL, updates, connections и certificate mode. После source logOut не входите снова на прежний source для диагностики — сверяйте target. До подтверждённого logOut не авторизуйте обе стороны. UNKNOWN может означать применённую мутацию: слепого повтора, rollback или polling fallback нет.

Exit 0 означает API acceptance и сверку читаемого профиля. Байты секрета/сертификата через readback не проверяются. Рост очереди — наблюдение, а не требование равенства счётчиков или доказательство потерь; исторические ошибки отличаются от новых delivery/synchronization errors. Нулевая очередь не доказывает доставку. Доставка остаётся unverified без нового коррелированного receiver receipt. Окно 10 секунд/два samples короче рекомендованного максимума 30 секунд; это не SLA. Не включайте debug/VLOG; logger/image qualification и реальная test-bot delivery — отдельные внешние гейты. Инструкции receiver, pinned-source и CI приведены в maintenance.
