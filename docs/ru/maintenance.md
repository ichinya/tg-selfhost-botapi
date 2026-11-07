---
title: Обслуживание
translation: /docs/en/maintenance.html
---

# Обслуживание

## Сборка образа

Workflow проверяет официальный исходник tdlib и digest Alpine 3.22 каждую ночь
около **04:37 Asia/Yekaterinburg** (23:37 UTC), при изменении основной ветки и
вручную. GitHub может задерживать запуск по расписанию.

Ключи пары учитывают ревизию/base digests, реальные recipes, runtime, fixtures,
тесты и документационные gates. Подтверждённые опубликованные кандидаты можно
получить без пересборки, но текущая квалификация выполняется заново. Подтверждённое
отсутствие manifest допускает сборку; UNKNOWN registry останавливает квалификацию.

Для каждой пары кандидатов workflow:

1. Проверяет применимость патча User-Agent к выбранной официальной ревизии.
2. Собирает отсутствующие образы одним compilation job с ограниченными ресурсами.
3. Выполняет unit, CLI, context/privacy, Jekyll и synthetic file-contract gates,
   включая offline TDLib probe и state isolation до/после opt-in.
4. Сохраняет точные image IDs Bot API/downloads в архиве с checksum.
5. Загружает архив без пересборки, публикует оба `build-<key>` образа, сверяет
   registry digest/image ID и затем продвигает их `latest`.

Ошибка квалификации оставляет прежний опубликованный `latest`. Из PR публикации
нет. Два registry tag продвигаются последовательно, без атомарной транзакции;
consumer должен фиксировать digests проверенной пары. Строка в бинарнике не
заменяет проверку доставки реального webhook, а публикация не означает deploy.

Для расписания и публикации workflow должен быть в основной ветке. Запись в GHCR
использует `GITHUB_TOKEN` с `packages: write`. После первого выпуска настройте
публичность пакета либо авторизацию клиентов.

## Обновление установки

Перед включением split storage остановите writer и readers, сделайте приватную
согласованную cold backup состояния, media, образа/конфигурации и владельцев/ACL.
Не переносите binlog или весь legacy state в media. Старые cache paths могут
оставаться в state и отклоняются новыми readers; автоматическая конвертация cache
и повторное скачивание Telegram не гарантируются. Возобновляйте работу после
проверки нового getFile path и изоляции. Rollback возвращает согласованные backup,
конфигурацию и образ, сохраняя state недоступным readers и proxy.

Для существующего remote profile сначала остановите всех readers и writer;
local readers должны завершиться и оставаться выключенными. Backup храните вне
обоих roots:

```sh
docker compose -f docker-compose.yml -f docker-compose.downloads.yml stop downloads downloads-gateway botapi
# BACKUP_DIR — существующий приватный каталог оператора вне ./data и ./files.
sudo tar --numeric-owner --acls --xattrs -cpf "$BACKUP_DIR/storage.tar" data files
```

Сохраните рядом приватно `.env`, registry, token-файлы и image digests с mode,
владельцами и ACL. Подготовьте только новые media/bot roots, запустите согласованную
пару и проверьте bytes/hash, read-only и отказ legacy path до возобновления клиентов.
При rollback снова остановите всё, верните полный cold set, а не смесь старого
state с новым media, проверьте владельцев и сохраните state закрытым.
Синтетический rehearsal проверяет bytes/ownership и rollback заполненного layout,
но не подтверждает Telegram session continuity или historical re-download.
Отдельный offline harness закреплённых исходников TDLib/tdutils проверяет
create/rename downloaded media и права reader. До его успешного Linux-прогона
это доказательство UNKNOWN и публикация закрыта.

Публикация в registry не перезапускает VPS. Выберите проверенный тег/digest через
`BOTAPI_IMAGE` в `.env`, затем:

```sh
docker compose stop botapi
# Здесь сделайте согласованную копию ./data, ./files и приватной конфигурации.
docker compose pull botapi
docker compose up -d --no-deps botapi
docker compose logs --tail=100 botapi
```

Для локальной сборки последовательно используйте build override:

```sh
docker compose -f docker-compose.yml -f docker-compose.build.yml stop botapi
# До замены бинарника сохраните ./data, ./files и приватную конфигурацию.
docker compose -f docker-compose.yml -f docker-compose.build.yml build botapi
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --no-deps botapi
```

Сохраните `./data`, `./files`, владельца `101:101`, endpoint и local mode.
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
