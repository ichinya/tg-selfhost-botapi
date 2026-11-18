#!/bin/sh
# Runs in the candidate image, after its unmodified production entrypoint.
# Default bootstrap has already initialized empty roots and used su-exec to 101:101.
# Existing contents are not chowned; retain the fixed 101:101 fixture assertions.
set -eu
if [ "$(id -u)" = 0 ]; then
    exec su -s /bin/sh telegram-bot-api -c 'exec /usr/local/bin/telegram-bot-api --fixture-child'
fi
test "$(id -u)" = 101
test "$(id -g)" = 101
umask 077
test -n "$FIXTURE_RUN_ID"
test -r "$TELEGRAM_WORK_DIR"
probe="$TELEGRAM_WORK_DIR/.write-probe-$$"
printf writable > "$probe"
rm -f "$probe"
if [ ! -f "$TELEGRAM_WORK_DIR/persistent-sentinel" ]; then
    printf 'persistent-%s' "$FIXTURE_RUN_ID" > "$TELEGRAM_WORK_DIR/persistent-sentinel"
fi
if [ ! -f "$TELEGRAM_TEMP_DIR/temp-sentinel" ]; then
    printf 'temporary-%s' "$FIXTURE_RUN_ID" > "$TELEGRAM_TEMP_DIR/temp-sentinel"
fi
if [ "${FIXTURE_MODE:-stay}" = fail ]; then
    exit 73
fi
trap 'exit 0' TERM INT
while :; do sleep 1; done
