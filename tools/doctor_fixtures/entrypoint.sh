#!/bin/sh
set -eu
if [ "$#" -gt 0 ]; then exec /usr/local/bin/telegram-bot-api "$@"; fi
exec /usr/local/bin/telegram-bot-api \
    "--dir=$TELEGRAM_WORK_DIR" "--temp-dir=$TELEGRAM_TEMP_DIR" \
    --http-port=8081 --local
