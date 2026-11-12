#!/bin/sh
# Synthetic upstream-shaped permissions, not a Telegram download.
set -eu
umask 0027
test "$(id -u):$(id -g)" = 1000:2000
media=/var/lib/telegram-bot-api-files
mkdir -p "$media/synthetic-bot/temp" "$media/synthetic-bot/documents" "$media/other-bot/documents"
test "$(stat -c %a "$media/synthetic-bot/documents")" = 750
printf 'synthetic-media\n' > "$media/synthetic-bot/temp/sample"
test "$(stat -c %a "$media/synthetic-bot/temp/sample")" = 640
test "$(stat -c %g "$media/synthetic-bot/temp/sample")" = 2000
test "$(stat -c %d "$media/synthetic-bot/temp")" = "$(stat -c %d "$media/synthetic-bot/documents")"
inode=$(stat -c %d:%i "$media/synthetic-bot/temp/sample")
mv "$media/synthetic-bot/temp/sample" "$media/synthetic-bot/documents/sample"
test "$(stat -c %d:%i "$media/synthetic-bot/documents/sample")" = "$inode"
test "$(stat -c %u:%g:%a "$media/synthetic-bot/documents/sample")" = 1000:2000:640
sha256sum "$media/synthetic-bot/documents/sample" | cut -d ' ' -f 1
