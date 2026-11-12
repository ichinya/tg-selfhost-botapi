#!/bin/sh
set -eu

# No core dump can be considered a public diagnostics artifact.
ulimit -c 0
privacy_verbosity() {
    case "$1" in 0|1|2|3) ;; *) echo 'Unsupported diagnostic verbosity (expected 0..3)' >&2; exit 1 ;; esac
}
privacy_verbosity "${TELEGRAM_VERBOSITY:-0}"
next_verbosity=false
for argument in "$@"; do
    if [ "$next_verbosity" = true ]; then privacy_verbosity "$argument"; next_verbosity=false; continue; fi
    case "$argument" in
        --verbosity|--memory-verbosity|-v) next_verbosity=true ;;
        --verbosity=*|--memory-verbosity=*) privacy_verbosity "${argument#*=}" ;;
        -v*) privacy_verbosity "${argument#-v}" ;;
    esac
done
if [ "$next_verbosity" = true ]; then echo 'Missing diagnostic verbosity' >&2; exit 1; fi

# Explicit CLI arguments (for example --version) do not require API credentials.
# Informational invocations never need credentials or storage.
if [ "$#" = 1 ]; then
    case "$1" in --version|--help|-h) exec telegram-bot-api "$@" ;; esac
fi

storage_error() { echo 'Unsafe or conflicting split storage configuration' >&2; exit 1; }
canonical() {
    if printf '%s' "$1" | LC_ALL=C grep -q '[[:cntrl:]]'; then storage_error; fi
    case "$1" in /*) ;; *) storage_error ;; esac
    case "$1" in *\\*) storage_error ;; esac
    case "$1/" in /|//*|*//*|*/./*|*/../*) storage_error ;; esac
    [ "$1" != / ] || storage_error
    # Reject symlink ancestors, including for a not-yet-created leaf.
    candidate="$1"
    while [ "$candidate" != / ]; do
        [ ! -L "$candidate" ] || storage_error
        if [ -e "$candidate" ]; then
            [ "$(realpath "$candidate")" = "$candidate" ] || storage_error
        fi
        candidate="${candidate%/*}"
        [ -n "$candidate" ] || candidate=/
    done
}
separate() {
    case "$1/" in "$2/"*) storage_error ;; esac
    case "$2/" in "$1/"*) storage_error ;; esac
}
validate_storage() {
    [ -n "$files" ] || return 0
    umask 007
    canonical "$files"; canonical "$work"; canonical "$temp"
    separate "$files" "$work"; separate "$files" "$temp"
    if [ -n "$log" ]; then canonical "$log"; separate "$files" "$log"; fi
    for secret in "${TELEGRAM_API_ID_FILE:-}" "${TELEGRAM_API_HASH_FILE:-}"; do
        if [ -n "$secret" ]; then canonical "$secret"; separate "$files" "$secret"; fi
    done
}

files=${TELEGRAM_FILES_DIR:-}
work=${TELEGRAM_WORK_DIR:-}
temp=${TELEGRAM_TEMP_DIR:-}
log=${TELEGRAM_LOG_FILE:-}
if [ "$#" -gt 0 ]; then
    # Only directory/log flags are parsed. Long-form flags are required in split mode.
    cli_files= cli_work= cli_temp= cli_log= seen=' '
    pending=
    for argument in "$@"; do
        if [ -n "$pending" ]; then flag=$pending; value=$argument; pending=
        else
            case "$argument" in
                --files-dir|--dir|--temp-dir|--log) pending=$argument; continue ;;
                --files-dir=*|--dir=*|--temp-dir=*|--log=*) flag=${argument%%=*}; value=${argument#*=} ;;
                -f|-f?*) storage_error ;;
                *) continue ;;
            esac
        fi
        case "$seen" in *" $flag "*) storage_error ;; esac
        seen="$seen$flag "; [ -n "$value" ] || storage_error
        case "$flag" in --files-dir) cli_files=$value ;; --dir) cli_work=$value ;;
            --temp-dir) cli_temp=$value ;; --log) cli_log=$value ;; esac
    done
    [ -z "$pending" ] || storage_error
    if [ -n "$files$cli_files" ]; then
        [ -n "$cli_files" ] && [ -n "$cli_work" ] && [ -n "$cli_temp" ] || storage_error
        for argument in "$@"; do case "$argument" in --*) ;; -*) storage_error ;; esac; done
        [ -z "$files" ] || [ "$files" = "$cli_files" ] || storage_error
        [ -z "$work" ] || [ "$work" = "$cli_work" ] || storage_error
        [ -z "$temp" ] || [ "$temp" = "$cli_temp" ] || storage_error
        [ -z "$log" ] || [ "$log" = "$cli_log" ] || storage_error
        files=$cli_files; work=$cli_work; temp=$cli_temp; log=$cli_log
        validate_storage
    fi
    exec telegram-bot-api "$@"
fi

validate_storage

load_secret() {
    secret_name="$1"
    secret_value="$(printenv "$secret_name" || true)"
    secret_file="$(printenv "${secret_name}_FILE" || true)"
    if [ -n "$secret_value" ] && [ -n "$secret_file" ]; then
        echo "Set either $secret_name or ${secret_name}_FILE, not both" >&2
        exit 1
    fi
    if [ -n "$secret_file" ]; then
        if ! secret_value="$(cat "$secret_file" 2>/dev/null)"; then
            echo "Cannot read $secret_name file" >&2
            exit 1
        fi
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
if [ -n "$files" ]; then
    mkdir -p "$files"
    chown telegram-bot-api:telegram-bot-api "$files"
fi

set -- "--dir=$TELEGRAM_WORK_DIR" "--temp-dir=$TELEGRAM_TEMP_DIR" \
    --username=telegram-bot-api --groupname=telegram-bot-api \
    "--http-port=${TELEGRAM_HTTP_PORT:-8081}"
if [ -n "$files" ]; then set -- "$@" "--files-dir=$files"; fi

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
