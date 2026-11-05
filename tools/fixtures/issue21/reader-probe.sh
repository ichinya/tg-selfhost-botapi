#!/bin/sh
set -eu
test "$(id -u)" = 3000
test "$(id -g)" = 3000
case " $(id -G) " in *' 2000 '*) ;; *) exit 1 ;; esac
printf 'reader uid=%s gid=%s groups=%s\n' "$(id -u)" "$(id -g)" "$(id -G)"
test "$(cat "$MEDIA_PATH/allowed.txt")" = issue21-reader
test "$(cat "$MEDIA_PATH/renamed.txt")" = issue21-reader
deny() {
    if "$@" >/dev/null 2>&1; then
        echo 'Reader unexpectedly allowed a forbidden operation' >&2
        exit 1
    fi
}
deny cat "$MEDIA_PATH/private.txt"
deny touch "$MEDIA_PATH/forbidden"
deny sh -c 'printf altered >> "$MEDIA_PATH/allowed.txt"'
deny rm "$MEDIA_PATH/allowed.txt"
test ! -e /private-state/canary
test ! -e /work/data/private-canary
test ! -e /work/data/other-bot/canary
test ! -e /work/temp
test ! -e "$MEDIA_PATH/../private-canary"
test ! -e "$MEDIA_PATH/../../private-canary"
test ! -e "$MEDIA_PATH/../../other-bot/canary"
test ! -e "$MEDIA_PATH/../../../temp"
