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

: "${TELEGRAM_WORK_DIR:?TELEGRAM_WORK_DIR is required}"
: "${TELEGRAM_TEMP_DIR:?TELEGRAM_TEMP_DIR is required}"
uid="$(id -u)"
gid="$(id -g)"
umask 0027
for dir in "$TELEGRAM_WORK_DIR" "$TELEGRAM_TEMP_DIR"; do
    if ! mkdir -p "$dir"; then
        echo "Cannot prepare directory $dir as $uid:$gid" >&2
        exit 1
    fi
    if [ "$uid" = 0 ]; then
        if ! chown telegram-bot-api:telegram-bot-api "$dir"; then
            echo "Cannot change ownership of $dir as $uid:$gid" >&2
            exit 1
        fi
    elif [ ! -w "$dir" ] || [ ! -x "$dir" ]; then
        echo "Directory $dir is not writable and searchable as $uid:$gid" >&2
        exit 1
    fi
done

set -- "--dir=$TELEGRAM_WORK_DIR" "--temp-dir=$TELEGRAM_TEMP_DIR" \
    "--http-port=${TELEGRAM_HTTP_PORT:-8081}"
if [ "$uid" = 0 ]; then
    set -- "$@" --username=telegram-bot-api --groupname=telegram-bot-api
fi

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

exec telegram-bot-api "$@"
