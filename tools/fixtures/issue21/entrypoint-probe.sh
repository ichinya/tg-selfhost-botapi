#!/bin/sh
set -eu
printf 'identity=%s:%s\n' "$(id -u)" "$(id -g)"
printf 'arg=%s\n' "$@"
touch "$TELEGRAM_WORK_DIR/fixture-probe" "$TELEGRAM_TEMP_DIR/fixture-probe"
stat -c '%u:%g:%a' "$TELEGRAM_WORK_DIR/fixture-probe" "$TELEGRAM_TEMP_DIR/fixture-probe"
