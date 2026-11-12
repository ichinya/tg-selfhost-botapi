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
umask 0027
: "${TELEGRAM_WORK_DIR:?TELEGRAM_WORK_DIR is required}"
: "${TELEGRAM_TEMP_DIR:?TELEGRAM_TEMP_DIR is required}"

# Reject aliases and symlink components before touching a configured root.
check_path() {
    path=$1
    case "$path" in
        /|''|*[!/]//*) echo "Invalid $2 directory; use a dedicated absolute path" >&2; exit 1 ;;
        /*) ;;
        *) echo "Invalid $2 directory; use a dedicated absolute path" >&2; exit 1 ;;
    esac
    case "/${path#/}/" in */./*|*/../*|*//* )
        echo "Invalid $2 directory; use a dedicated absolute path" >&2; exit 1 ;;
    esac
    rest=${path#/}
    component_path=
    while [ -n "$rest" ]; do
        component=${rest%%/*}
        if [ "$rest" = "$component" ]; then rest=; else rest=${rest#*/}; fi
        component_path="$component_path/$component"
        if [ -L "$component_path" ]; then
            echo "Invalid $2 directory; symlinks are not supported" >&2; exit 1
        fi
    done
}

prepare_root() {
    path=$1
    role=$2
    check_path "$path" "$role"
    if [ ! -e "$path" ]; then
        mkdir -p -m 700 "$path" 2>/dev/null || { echo "Cannot create $role directory" >&2; exit 1; }
    fi
    [ -d "$path" ] || { echo "Invalid $role directory" >&2; exit 1; }
    if [ "$(id -u)" = 0 ]; then
        # Include dotfiles; never traverse or repair existing contents.
        check_path "$path" "$role"
        entries=$(find "$path" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null) || {
            echo "Cannot inspect $role directory" >&2; exit 1;
        }
        if [ -z "$entries" ]; then
            chown 101:101 "$path" 2>/dev/null && chmod 700 "$path" 2>/dev/null || {
                echo "Cannot initialize $role directory" >&2; exit 1;
            }
        fi
    fi
}

if [ -n "${TELEGRAM_FILES_DIR:-}" ]; then
    check_path "$TELEGRAM_WORK_DIR" state
    check_path "$TELEGRAM_TEMP_DIR" temp
    check_path "$TELEGRAM_FILES_DIR" media
    disjoint_roots() {
        left=$1; right=$2
        case "$left/" in "$right/"|"$right/"*) echo "Storage roots must be separate" >&2; exit 1 ;; esac
        case "$right/" in "$left/"*) echo "Storage roots must be separate" >&2; exit 1 ;; esac
    }
    disjoint_roots "$TELEGRAM_WORK_DIR" "$TELEGRAM_TEMP_DIR"
    disjoint_roots "$TELEGRAM_WORK_DIR" "$TELEGRAM_FILES_DIR"
    disjoint_roots "$TELEGRAM_TEMP_DIR" "$TELEGRAM_FILES_DIR"
    if [ "${BOTAPI_MEDIA_REQUIRE_NONROOT:-}" = 1 ]; then
        if [ "$(id -u)" = 0 ] || [ "$(id -u)" != "${BOTAPI_MEDIA_EXPECTED_UID:-}" ] || [ "$(id -g)" != "${BOTAPI_MEDIA_EXPECTED_GID:-}" ]; then
            echo "Media override requires the configured non-root Docker user and primary group" >&2; exit 1
        fi
    fi
fi

prepare_root "$TELEGRAM_WORK_DIR" state
prepare_root "$TELEGRAM_TEMP_DIR" temp
if [ -n "${TELEGRAM_FILES_DIR:-}" ]; then prepare_root "$TELEGRAM_FILES_DIR" media; fi
if [ "$(id -u)" = 0 ]; then
    exec su-exec 101:101 /docker-entrypoint.sh
fi

probe_root() {
    path=$1
    role=$2
    # The probe is exclusive and only our own file is removed.
    (cd "$path" && ls -a . >/dev/null) 2>/dev/null || {
        echo "Cannot access $role directory; prepare it for the server identity" >&2; exit 1;
    }
    probe="$path/.botapi-write-probe-$$"
    (set -C; : > "$probe") 2>/dev/null || {
        echo "Cannot write $role directory; prepare it for the server identity" >&2; exit 1;
    }
    rm "$probe" 2>/dev/null || { echo "Cannot clean up $role directory probe" >&2; exit 1; }
}
probe_root "$TELEGRAM_WORK_DIR" state
probe_root "$TELEGRAM_TEMP_DIR" temp
if [ -n "${TELEGRAM_FILES_DIR:-}" ]; then probe_root "$TELEGRAM_FILES_DIR" media; fi

load_secret() {
    secret_name="$1"
    secret_value="$(printenv "$secret_name" || true)"
    secret_file="$(printenv "${secret_name}_FILE" || true)"
    if [ -n "$secret_value" ] && [ -n "$secret_file" ]; then
        echo "Set either $secret_name or ${secret_name}_FILE, not both" >&2
        exit 1
    fi
    if [ -n "$secret_file" ]; then
        secret_value="$(cat "$secret_file" 2>/dev/null)" || {
            echo "Cannot read ${secret_name}_FILE as the server user" >&2; exit 1;
        }
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

set -- "--dir=$TELEGRAM_WORK_DIR" "--temp-dir=$TELEGRAM_TEMP_DIR" \
    "--http-port=${TELEGRAM_HTTP_PORT:-8081}"
if [ -n "${TELEGRAM_FILES_DIR:-}" ]; then set -- "$@" "--files-dir=$TELEGRAM_FILES_DIR"; fi

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
