#!/bin/sh
# Check the exact selected source, not a mutable online copy or a downloaded file.
set -eu
source=/usr/src/telegram-bot-api
test "$(git -C "$source" rev-parse HEAD)" = "$BOT_API_REVISION"
td_revision=$(git -C "$source" rev-parse HEAD:td)
test "$(git -C "$source/td" rev-parse HEAD)" = "$td_revision"
loader="$source/td/td/telegram/files/FileLoaderUtils.cpp"
grep -Eq 'FileFd::open\(name,.*CreateNew, 0640\)' "$loader"
grep -Fq 'mkdir(path, 0750)' "$loader"
grep -Fq 'auto temp_dir = get_files_temp_dir(file_type)' "$loader"
grep -Fq 'try_create_new_file(temp_dir,' "$loader"
grep -Fq 'rename(temp_path, perm_path)' "$loader"
grep -Eq 'get_files_base_dir\(file_type\).*"temp"' "$loader"
grep -Eq 'get_files_base_dir\(file_type\).*get_file_type_name' "$loader"
printf 'source=%s td=%s\n' "$BOT_API_REVISION" "$td_revision"
sha256sum "$loader"
