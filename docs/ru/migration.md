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
Старое имя Bash сохраняется и передаёт субкоманды общему CLI. В вызовах с
`--опциями` позиционные token/target/webhook отклоняются без вывода значений; используйте environment
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

Корневой скрипт ограничивает каждый запрос настройками `MIGRATION_CONNECT_TIMEOUT`
и `MIGRATION_REQUEST_DEADLINE`; значения, диапазоны и приоритет описаны в
[конфигурации](configuration.md). Проверка без токена ограничена 10 секундами.

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

Официальная процедура переноса состояния бота: `deleteWebhook`, затем `close` на
старом сервере, после чего перенос подкаталога бота (по его user ID) в рабочий
каталог нового сервера. После переноса продолжайте запросы на новом сервере.
Если `close` вернул `retry_after`, обработайте ожидание до следующих действий.

Нужны согласованная резервная копия, сохранение владельца и путей, а также запрет
одновременной работы с одним состоянием. Одно лишь `drop_pending_updates=false`
не переносит данные и не гарантирует непрерывность.

Общие `tqueue.binlog` и `webhooks_db.binlog` находятся вне каталогов отдельных ботов. Перенос каталога одного бота не доказывает сохранность локальной очереди. Обработайте backlog заранее или явно учтите его потерю; слияние общих binlog с работающим сервером других ботов не поддерживается. `drop_pending_updates=false` не гарантирует сохранность очереди.

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

## Совместимость адаптера

Используйте `bash tools/migration_executor.sh plan/apply/status/resume/reconcile/export ...`
с теми же флагами, что Python. Для самой миграции curl/jq не нужны.
Файлы `.env` и `.env.example` репозитория предназначены только для Compose.
Параметры миграции передавайте через environment или отдельный приватный файл
с явным `--env-file`; executor автоматически `.env` не читает.
Environment имеет приоритет. Пустой webhook требует явного action и в legacy-mode.
Используйте `BOT_TOKEN` или `BOT_TOKEN_FILE`; позиционные credentials
отклоняются при вызове с `--опциями`. Отдельный корневой `migrate_off_to_self.sh` сохраняет
контракт [standalone-утилиты](#bash-утилита). Состояние и блокировки двух исполнителей раздельны.
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

Для реального `webhook_only` на официальном облаке требуемые доказательства локального развёртывания недоступны, поэтому исполнитель блокирует операцию. Проверка готовности облака применяется только к `local_to_cloud`.

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
[изолированный mock walkthrough](maintenance.md#изолированный-пример-с-mock-сервером).

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
- Helper ? ??????? ????????? ?????? ???????? ??????? ?? ????????? source.
  ??????? ?????? ? ????????? ?????????? ???????? ????: WebhookInfo ?? ?????????? ??? ??????.
- ?????? ????? ???? ????? ? ?????????? ????????? ? ??????? ????????. ???????????
  ??????? ? ??????????????? ????????? helper ?????????; ????????? raw ???????? ?????????.

Исправления отслеживаются в [#2](https://github.com/ichinya/tg-selfhost-botapi/issues/2),
[#7](https://github.com/ichinya/tg-selfhost-botapi/issues/7) и
[#9](https://github.com/ichinya/tg-selfhost-botapi/issues/9).
Перед использованием с работающей установкой проверьте процедуру на тестовом боте.

### Ограничения запросов (корневой Bash helper)

`MIGRATION_CONNECT_TIMEOUT`: по умолчанию 5 секунд, диапазон 1..60;
`MIGRATION_REQUEST_DEADLINE`: по умолчанию 30 секунд, диапазон 1..300. Допустимы
целые десятичные секунды, connect не больше deadline. Deadline ограничивает одну
HTTP-попытку вместе с получением тела; ожидание ответа оператора в него не входит.
Для проверки без токена применяются min(deadline, 10) и connect не больше этого лимита.

Доверенный загрузчик файла поддерживает обе настройки. Значение процесса важнее
файла; default применяется только к незаданной переменной. Явно пустое значение —
ошибка, в отличие от прежнего fallback пустых настроек адресов. Неверные значения
останавливают выполнение до HTTP. Это настройки хоста, они не передаются через
Compose в контейнер. См. [миграцию](migration.md).

### Исходы и приватная диагностика

Корневой Bash helper сохраняет досье schema version 1 в `logs/migration` рядом
со скриптом, независимо от каталога вызова. Каталоги принадлежат пользователю и
имеют права 0700, файлы — 0600 (`umask 077`). Небезопасные существующие пути и
symlink останавливают запуск до HTTP. Уникальный каталог `run.*` содержит
`summary.json` со ссылками на `request-*.*/intent.json` до каждой HTTP-попытки и
`receipt.json` после неё. Receipt ссылается на отдельные полные очищенные
`body.txt`, `transport-error.txt` и `http-status.txt`. HTTP-статус, код curl,
parse/schema status, API-поля, фактические лимиты, время, наблюдения и исход
независимы. Статус 000 становится null; транспортный сбой может сохранить
HTTP-статус и частичное тело. Очищенный текст не является побайтовым оригиналом:
управляющие символы, JSON и экранированные секреты нормализуются.

Успех требует завершённого транспорта, HTTP 2xx, boolean `ok:true` и корректного
result метода. Полный валидный отказ при HTTP 2xx/4xx — `CONFIRMED_REJECTION`
(exit 1); при 429 выводится `retry_after` без ожидания и повтора. HTTP 5xx,
неполные или противоречивые ответы и потеря ответа любого запроса с токеном дают
`UNKNOWN` (exit 3). Даже `getMe` и `getWebhookInfo` могут влиять на сессию.
После UNKNOWN нет зависимых запросов, readback, rollback или автоматического
повтора. Локальная ошибка до отправки — `NOT_SENT`; успех и отказ оператора
завершаются с exit 0. Ожидаемый token-free 404 probe проверяется отдельно от
успеха метода и не подтверждает подлинность хоста.

Атомарный lock всего storage root берётся до анализа прошлых запусков и probe.
Активный/stale lock, незавершённый intent запроса с токеном, UNKNOWN или частичная
миграция блокируют новый запуск до HTTP. Защита действует для одной копии скрипта
и всех ботов в её storage root. Подтверждённые шаги и эффекты остаются в summary
после последующего отказа. Остановитесь и сопоставьте досье с независимыми данными;
ожидание `retry_after`, повтор `getMe` или чтение URL не доказывают отсутствие
предыдущего эффекта. Автоматического обхода и готового resume нет.

Незавершённый probe без токена не блокирует запуск после освобождения его lock.
Любой сохранившийся lock блокирует, в том числе после SIGKILL. Для восстановления
сначала остановите все процессы helper и сопоставьте попытки и подтверждённые
эффекты с независимыми данными. Определив безопасную дальнейшую процедуру,
архивируйте всё досье в приватном месте вне `logs/migration`, затем осознанно
удалите проверенные каталоги запусков и stale lock. Храните архив до разрешения
миграции. Удаление одного lock не заменяет reconciliation; копия скрипта в другом
каталоге не делает повтор неизвестного эффекта безопасным. Это ручная граница
восстановления до реализации issue #2.

Raw capture приватен и удаляется только после успешной очистки. Авария, SIGKILL
и ошибка хранилища могут оставить приватный raw или незавершённый intent;
сохраняйте и анализируйте их локально. Не загружайте raw и досье в публичные
issue. Retention — до осознанного ручного удаления после reconciliation.
Журнал использует atomic rename, без гарантии fsync durability. Для issue #2
нужен явный адаптер этой схемы; журналы разных executor не взаимозаменяемы.
Контракт относится только к `migrate_off_to_self.sh`: browser execution,
generated Bash и raw-curl runbook имеют отдельные контракты.
Ручные curl-примеры не создают досье и не реализуют guard.
Обновлённый helper берите из актуального checkout репозитория. Он работает на
хосте, исключён из server image и Pages; повторное развёртывание сервера не требуется.

## Браузерный инструмент

Операция хранит план и наблюдения раздельно в текущей вкладке. SUCCESS требует
подтверждённого итогового URL на target и не доказывает доставку. Журнал этапов
существует только на странице и не заменяет долговременное восстановление из #2.
Отказ от согласия не создаёт операцию.
Подтверждённый отказ Bot API отличается от недостоверного или потерянного
ответа, эффект которого может быть UNKNOWN. Корректный `retry_after` задаёт
время ожидания; его истечение не запускает повтор и не разрешает неопределённый
исход. Окно 429 для local `close` отличается от ограничения возврата в cloud
после `logOut`.
Во время ожидания страница выдаёт инструкцию вместо исполняемых команд; его
истечение не снимает отдельный запрет на повтор до сверки.
Результат различает ERROR, PARTIAL и UNKNOWN и SUCCESS. ID бота на source и
target должны совпасть, а итоговый URL читается с target, а не подставляется из
запроса. Итог разделяет наблюдение source, ожидаемый URL, наблюдение target и
журнал этапов. Пути и параметры URL webhook маскируются в итоге и истории.
После ошибки или неизвестного исхода logout действуйте по восстановлению
из #2; не входите повторно на source только ради проверки.
Вкладка блокирует одновременные действия и хранит ограничения восстановления
по ботам в памяти. Изменение настроек сбрасывает проверку. Закрытие или
перезагрузка вкладки удаляет ограничения; координация процессов остаётся за
пределами инструмента (#2 и #14). После завершённого переноса новая операция
webhook-only допустима на подтверждённом target; прежний source остаётся
заблокированным в этой вкладке.
Сгенерированный Bash-план останавливается при ошибках и сообщает этап и исход;
он сравнивает ID ботов и итоговый URL. Это отдельный процесс без общего lock и
долговременного состояния со страницей. Перед повтором PARTIAL или UNKNOWN
требует сверки; истечение ожидания не перезапускает план автоматически.

Сгенерированный Bash-план отдельно запрашивает URL webhook и не копирует его из
формы в скрипт. Пустой ввод означает наследование URL исходного сервера.

[Открыть мигратор](../../tg_selfhost_botapi_migrator.html). Это статическая страница,
а не серверный исполнитель миграции. Запросы идут из вашего браузера; API должен
разрешать соответствующий origin и доступ.

Локальные проверки и построение плана не отправляют запросов. Проверка состояния
требует согласия и читает только явно выбранный source, не определяя текущий
сервер бота. Cloud → local проверяет target без токена, запрашивает согласие,
читает source, отключает там webhook и выходит, затем обращается к target.
Webhook-only не вызывает `logOut` и `close`. Изменение формы сбрасывает прочитанное
состояние. Частичный или неизвестный исход блокирует дальнейшее выполнение для
этого бота во вкладке до ручной сверки. Известный отказ до изменений допускает
повтор после необходимого ожидания. Локальные переходы выполняются по чеклистам.

В выполнении и генераторе плана остаются не полностью проверенные ограничения
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

Браузер использует password/File controls и не сохраняет private inputs в storage. Preflight браузера проверяет только структуру X.509, а не криптографическую корректность; сертификат проверяется target API при принятии. Helper дополнительно проверяет X.509 через openssl. Экспорт требует повторного ввода private inputs при запуске и не содержит browser token, secret, URL, байты сертификата или настоящее имя private file. Ручной план содержит безусловный STOP/exit перед отдельным сохраняемым target-stage script; перенос state он не выполняет. Для target-stage нужны явные сохранённые URL, updates, connections и certificate mode. После source logOut не входите снова на прежний source для диагностики — сверяйте target. До подтверждённого logOut не авторизуйте обе стороны. UNKNOWN может означать применённую мутацию: слепого повтора, rollback или polling fallback нет.

Exit 0 означает API acceptance и сверку читаемого профиля. Байты секрета/сертификата через readback не проверяются. Рост очереди — наблюдение, а не требование равенства счётчиков или доказательство потерь; исторические ошибки отличаются от новых delivery/synchronization errors. Нулевая очередь не доказывает доставку. Доставка остаётся unverified без нового коррелированного receiver receipt. Окно 10 секунд/два samples короче рекомендованного максимума 30 секунд; это не SLA. Не включайте debug/VLOG; logger/image qualification и реальная test-bot delivery — отдельные внешние гейты. Инструкции receiver, pinned-source и CI приведены в maintenance.

Автономный экспорт выполняется в Bash 4+ в Linux или WSL. Значения из браузера не включаются в файл; повторно задайте входные данные при запуске. URL с пробелами или управляющими символами отклоняются без обрезки.

URL исходного webhook с управляющими символами отклоняется до изменяющих запросов миграции.
