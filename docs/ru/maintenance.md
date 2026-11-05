---
title: Обслуживание
translation: /docs/en/maintenance.html
---

# Обслуживание

## Сборка образа

Workflow проверяет официальный исходник tdlib и digest Alpine 3.22 каждую ночь
около **04:37 Asia/Yekaterinburg** (23:37 UTC), при изменении основной ветки и
вручную. GitHub может задерживать запуск по расписанию.

Ключ сборки учитывает ревизии/digest, рецепт, entrypoint, патч, Compose-файлы,
permissions runner и все acceptance fixtures issue-21. Если соответствующий образ
уже опубликован, компиляция пропускается, а candidate загружается по registry
digest. Проверяются labels build-key и ревизии, затем повторяются те же smoke и
runtime gates. Если registry не подтвердил образ, выполняется новая сборка.

Для нового образа workflow:

1. Проверяет применимость патча User-Agent к выбранной официальной ревизии.
2. Компилирует весь сервер.
3. Выполняет `--version`, проверяет строку заголовка в бинарнике и синтаксис entrypoint.
4. Выполняет обязательную Linux-матрицу прав, включая ограниченный reader.
5. Публикует `ghcr.io/ichinya/tg-selfhost-botapi:build-<key>`, сверяет digest с
   проверенным local image ID и продвигает этот digest в `latest`.

Ошибка проверки оставляет прежний опубликованный `latest`. Из PR публикации нет.
Наличие строки в бинарнике не заменяет проверку доставки реального webhook.

Для расписания и публикации workflow должен быть в основной ветке. Запись в GHCR
использует `GITHUB_TOKEN` с `packages: write`. После первого выпуска настройте
публичность пакета либо авторизацию клиентов.

## Обновление установки

Если запуск использовал `docker-compose.nonroot.yml`, добавляйте
`-f docker-compose.yml -f docker-compose.nonroot.yml` в каждую команду
обновления из registry ниже. Для локальной сборки добавляйте
`-f docker-compose.nonroot.yml` после build override в каждую команду.

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

Сохраните `./data`, владельца, совместимого с выбранным пользователем сервера,
endpoint и local mode. Root bootstrap по умолчанию использует `101:101`, прямой
non-root запуск — настроенные Docker UID:GID.
Не запускайте два процесса Bot API с одним каталогом данных. Для возврата старого
образа может понадобиться совместимая резервная копия состояния: одного отката
бинарника недостаточно для гарантии.

После обновления проверьте журналы и отправьте тестовое сообщение боту,
который уже работает на этом сервере. Проверьте фактический webhook, состояние
доставки и User-Agent в журнале принимающего сервиса.

## Диагностика

На Linux rootful Docker с POSIX filesystem (`linux/amd64`) проверьте загруженный
candidate командой `python3 tools/check_runtime_permissions.py --image
botapi-candidate:check`. Runner использует только временные named volumes и bind
каталоги вне checkout, синтетические credentials и изолированные Compose services
без сети и опубликованных портов. Проверяются default/root, прямые числовые и
именованные пользователи, restart, старые данные, отдельные отказы write/search,
read-only, права секретов и журнала. Вывод содержит метаданные candidate и
различает `REAL_BINARY` startup/HTTP, `ENTRYPOINT_FIXTURE` и `GROUP_FILESYSTEM`
имитации. Отсутствие Docker, timeout или пропуск обязательного случая дают ошибку.
Rootless/userns-remap, Docker Desktop и ARM64 этот gate не квалифицирует.

Посторонний вложенный файл с несовместимым владельцем сам по себе не блокирует
startup. Runner отдельно проверяет отказ доступа и неизменность hash/owner/mode,
затем адаптирует только остановленную тестовую копию offline. Сервер не выполняет
рекурсивный audit или repair; экспериментальная политика `tools/ci_safety` не
является контрактом этого gate. Авторизация и загрузка реального бота не проверяются.

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

## Смена пользователя хранилища

Остановите единственный writer и всех readers, затем сделайте согласованную
резервную копию с владельцами и режимами. Запишите старые и новые UID:GID и
канонический корень хранилища. Меняйте нужное дерево только offline, не следуя
по symlinks и не переходя на другие mounts; проверьте вложенные файлы и оставшихся
старых владельцев. Не применяйте массовые рекурсивные изменения прав ко всему
state. Для нового каталога возможна точечная команда `install -d -m 0700 -o
1000 -g 2000 /srv/tg-selfhost-botapi/temp`. Подготовьте state и temp для
эффективного пользователя, чтение секретов `_FILE`, запись и проход в родителе
файла журнала. Проверяйте фактические create и rename: ACL или setgid сами по
себе этого не гарантируют. Запустите один writer и проверьте новые записи и старые
данные до запуска readers. Откат образа или пользователя отдельно от восстановления
совместимых владельцев или backup; не меняйте владельца работающего state и не
запускайте два writer.
