#!/bin/sh
set -eu

# Explicit CLI arguments (for example --version) do not require API credentials.
if [ "$#" -gt 0 ]; then
    exec telegram-bot-api "$@"
fi

load_secret() {
    secret_name="$1"
    secret_value="$(printenv "$secret_name" || true)"
    secret_file="$(printenv "${secret_name}_FILE" || true)"
    if [ -n "$secret_value" ] && [ -n "$secret_file" ]; then
        echo "Set either $secret_name or ${secret_name}_FILE, not both" >&2
        exit 1
    fi
    if [ -n "$secret_file" ]; then
        secret_value="$(cat "$secret_file")"
    fi
    if [ -z "$secret_value" ]; then
        echo "$secret_name is required" >&2
        exit 1
    fi
    export "$secret_name=$secret_value"
}

load_secret TELEGRAM_API_ID
load_secret TELEGRAM_API_HASH

case "${TELEGRAM_HTTP_PORT:-8081}" in
    ''|0*|*[!0-9]*|8082|8090) echo 'Invalid or conflicting HTTP port' >&2; exit 1 ;;
esac
[ "${TELEGRAM_HTTP_PORT:-8081}" -ge 1 ] && [ "${TELEGRAM_HTTP_PORT:-8081}" -le 65535 ] || {
    echo 'Invalid HTTP port' >&2; exit 1;
}

: "${TELEGRAM_WORK_DIR:?TELEGRAM_WORK_DIR is required}"
: "${TELEGRAM_TEMP_DIR:?TELEGRAM_TEMP_DIR is required}"
mkdir -p "$TELEGRAM_WORK_DIR" "$TELEGRAM_TEMP_DIR"
chown telegram-bot-api:telegram-bot-api "$TELEGRAM_WORK_DIR" "$TELEGRAM_TEMP_DIR"

set -- "--dir=$TELEGRAM_WORK_DIR" "--temp-dir=$TELEGRAM_TEMP_DIR" \
    --username=telegram-bot-api --groupname=telegram-bot-api \
    "--http-port=${TELEGRAM_HTTP_PORT:-8081}"

# Quoted argument arrays preserve spaces and never execute environment contents.
for setting in \
    TELEGRAM_LOG_FILE:--log \
    TELEGRAM_FILTER:--filter \
    TELEGRAM_MAX_WEBHOOK_CONNECTIONS:--max-webhook-connections \
    TELEGRAM_VERBOSITY:--verbosity \
    TELEGRAM_MAX_CONNECTIONS:--max-connections \
    TELEGRAM_PROXY:--proxy \
    TELEGRAM_HTTP_IP_ADDRESS:--http-ip-address
do
    setting_name="${setting%%:*}"
    setting_flag="${setting#*:}"
    setting_value="$(printenv "$setting_name" || true)"
    if [ -n "$setting_value" ]; then
        set -- "$@" "$setting_flag=$setting_value"
    fi
done

for setting in TELEGRAM_LOCAL:--local TELEGRAM_STAT:--http-stat-port=8082
do
    setting_name="${setting%%:*}"
    setting_flag="${setting#*:}"
    setting_value="$(printenv "$setting_name" || true)"
    case "$setting_value" in
        1|true|TRUE) set -- "$@" "$setting_flag" ;;
        0|false|FALSE|'') ;;
        *) echo "$setting_name must be true/false or 1/0" >&2; exit 1 ;;
    esac
done

case "${TELEGRAM_STAT:-false}" in
    1|true|TRUE) set -- "$@" --http-stat-ip-address=127.0.0.1 ;;
esac

exec telegram-bot-api "$@"
