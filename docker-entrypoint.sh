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

storage_error() {
    echo 'Invalid split-storage configuration; check private roots and permissions' >&2
    exit 1
}

canonical_path() {
    case "$1" in
        /*) ;;
        *) storage_error ;;
    esac
    case "$1" in
        /|*/|*//*|*/./*|*/../*|*/.|*/..) storage_error ;;
    esac
    # Check every existing ancestor, including a symlink at the requested root.
    checked_path="$1"
    while [ "$checked_path" != / ]; do
        [ ! -L "$checked_path" ] || storage_error
        checked_path="${checked_path%/*}"
        [ -n "$checked_path" ] || checked_path=/
    done
}

disjoint_paths() {
    case "$1/" in "$2/"*) storage_error ;; esac
    case "$2/" in "$1/"*) storage_error ;; esac
}

if [ -n "${TELEGRAM_FILES_DIR:-}" ]; then
    canonical_path "$TELEGRAM_WORK_DIR"
    canonical_path "$TELEGRAM_TEMP_DIR"
    canonical_path "$TELEGRAM_FILES_DIR"
    disjoint_paths "$TELEGRAM_WORK_DIR" "$TELEGRAM_TEMP_DIR"
    disjoint_paths "$TELEGRAM_FILES_DIR" "$TELEGRAM_WORK_DIR"
    disjoint_paths "$TELEGRAM_FILES_DIR" "$TELEGRAM_TEMP_DIR"
    for private_root in /tmp /run /etc /proc /sys /dev; do
        disjoint_paths "$TELEGRAM_FILES_DIR" "$private_root"
    done
    for credential_file in "${TELEGRAM_API_ID_FILE:-}" "${TELEGRAM_API_HASH_FILE:-}"; do
        if [ -n "$credential_file" ]; then
            canonical_path "$credential_file"
            disjoint_paths "$TELEGRAM_FILES_DIR" "$credential_file"
        fi
    done
    if [ -n "${TELEGRAM_LOG_FILE:-}" ]; then
        case "$TELEGRAM_LOG_FILE" in
            /*) ;;
            *) TELEGRAM_LOG_FILE="$TELEGRAM_WORK_DIR/$TELEGRAM_LOG_FILE"; export TELEGRAM_LOG_FILE ;;
        esac
        canonical_path "$TELEGRAM_LOG_FILE"
        disjoint_paths "$TELEGRAM_FILES_DIR" "$TELEGRAM_LOG_FILE"
    fi
    umask 007
    if [ ! -e "$TELEGRAM_FILES_DIR" ]; then
        mkdir -p "$TELEGRAM_FILES_DIR"
        chown telegram-bot-api:telegram-bot-api "$TELEGRAM_FILES_DIR"
        chmod 770 "$TELEGRAM_FILES_DIR"
    fi
    [ -d "$TELEGRAM_FILES_DIR" ] || storage_error
    [ "$(stat -c %u:%g "$TELEGRAM_FILES_DIR")" = 101:101 ] || storage_error
    [ "$(stat -c %a "$TELEGRAM_FILES_DIR")" = 770 ] || storage_error
fi
mkdir -p "$TELEGRAM_WORK_DIR" "$TELEGRAM_TEMP_DIR"
chown telegram-bot-api:telegram-bot-api "$TELEGRAM_WORK_DIR" "$TELEGRAM_TEMP_DIR"

set -- "--dir=$TELEGRAM_WORK_DIR" "--temp-dir=$TELEGRAM_TEMP_DIR" \
    --username=telegram-bot-api --groupname=telegram-bot-api \
    "--http-port=${TELEGRAM_HTTP_PORT:-8081}"
if [ -n "${TELEGRAM_FILES_DIR:-}" ]; then
    set -- "$@" "--files-dir=$TELEGRAM_FILES_DIR"
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
