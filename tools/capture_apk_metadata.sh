#!/bin/sh
set -eu
stage=$1
refresh=$2
case "$stage" in build|runtime) ;; *) exit 1;; esac
test -n "$refresh"
path=/usr/share/tg-selfhost-botapi/$stage
mkdir -p "$path"
printf '1\n' > "$path/schema"
printf '%s\n' "$refresh" > "$path/refresh-id"
cp /lib/apk/db/installed "$path/installed"
cp /etc/apk/repositories "$path/repositories"
apk --version > "$path/apk-version"
apk --print-arch > "$path/arch"
cp /etc/apk/world "$path/world"
cp /etc/alpine-release "$path/alpine-release"
