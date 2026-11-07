# File profile source examples / Исходники файловых профилей

These files are repository examples, excluded from the public Pages build.
Use Linux/amd64, kernel >= 5.6, a compatible qualified Bot API/downloads image
pair and working openat2 under the container's seccomp policy. Missing syscall
support stops startup; do not disable the policy or introduce a pathname fallback.
Do not put real tokens, derived directory names or download credentials in Git.

Long bind syntax uses `read_only: true` and `bind.create_host_path: false`, as
specified in the [Compose service reference](https://docs.docker.com/reference/compose-file/services/#long-syntax-5).
Context7 documentation lookup was unavailable (monthly quota); the official
Compose reference is the syntax source.

Before starting the shipped split profile, prepare the media root on Linux:

```sh
sudo install -d -o 101 -g 101 -m 0770 ./files
```

Read all paths below from your trusted private `.env`, not from untrusted input:

```sh
set -a
. ./.env
set +a
sudo install -d -o 101 -g 101 -m 2750 "$BOT_A_HOST_ROOT"
umask 077
# Privately provision the token file; the token is never a shell argument.
read -rsp 'Bot token: ' FILE_PROFILE_TOKEN; printf '\n'
printf '%s' "$FILE_PROFILE_TOKEN" > "$BOT_TOKEN_FILE"
unset FILE_PROFILE_TOKEN
sudo chown 0:101 "$BOT_TOKEN_FILE"
sudo chmod 0640 "$BOT_TOKEN_FILE"
```

Keep `.env` mode `0600`. Copy the registry template to `$DOWNLOADS_CONFIG_FILE`,
edit it privately, then set owner `0:101`, mode `0640`. Generate credentials with
`openssl rand -hex 32` redirected to a private file rather than terminal output.
Prepare the curl config with the same protections. Registry/token/curl files must
be outside media; the handler rejects a symlink, hardlink or permissive registry.

1. Start the split Bot API. Keep state `./data` and media `./files` disjoint.
   Resolve the actual full-token directory from this qualified revision; test DC
   appends `:T`, tilde layout replaces `:` with `~`. Mount the exact directory at
   the same absolute path in the reader. The getFile path is not a URL.
2. Prepare each bot directory on the host with writer UID/GID `101:101`, mode
   `2750`; writer umask is `007`. Reader UID/GID `10001:101` gets group read/traverse.
   Use an operator ACL if required, applied only to that bot directory. Never
   recursively chmod/chown all state or give the reader the parent media mount.
3. Store the bot token in a separate protected file, mode `0640`, owned by root
   or the reader and group `101`. Set the private variables shown in `.env.example`.
   Existing bind sources are required; a typo must fail instead of making an empty root.
4. Local read (use a nonsecret synthetic file ID while testing):

   ```sh
   docker compose -f docker-compose.yml -f examples/files/compose.local.yml run --rm reader '<FILE_ID>' > downloaded.bin
   ```

5. Remote opt-in: copy `downloads.config.example.json` to the gitignored
   `downloads.config.json`, replace every placeholder privately, bind alias,
   full token/DC and root exactly. Generate a separate random credential of at
   least 32 characters for each bot. Registry mode `0640`, owner root/reader,
   group `101`, no symlinks or hardlinks, outside media. Only the handler mounts it.
   For multiple bots, add a separate read-only bind for every registry entry.

   ```sh
   docker compose -f docker-compose.yml -f docker-compose.downloads.yml config --quiet
   docker compose -f docker-compose.yml -f docker-compose.downloads.yml up -d downloads downloads-gateway
   ```

6. The download proxy is loopback-only on `18082`; configure the host TLS example
   with operator certificates. Remote use requires HTTPS. Keep Authorization in
   a private curl configuration file, not shell history or the URL:

   ```sh
   curl --config /absolute/private/download.curl --fail-with-body \
     --header 'Content-Type: application/json' --data '{"file_id":"<FILE_ID>"}' \
     https://downloads.example.com/downloads/bot-a --output downloaded.bin
   ```

   The private curl file supplies `header = "Authorization: Bearer ..."` using
   the real credential outside this repository. The legacy token header is unused.

New response bytes are not a snapshot of a concurrently modified writer file.
If a file disappears, request again by file_id. No resume/range/HEAD is supported.
Rotate the private registry credential and recreate only downloads to revoke it.
The default gateway never depends on downloads and never mounts state or media.

Русский: примеры исключены из Pages. Нужны Linux/amd64, kernel >= 5.6 и openat2.
Используйте проверенную пару образов. Каталоги state/media разделены; consumer
получает read-only mount только своего полного token/DC каталога по тому же
абсолютному пути. Writer `101:101`, reader `10001:101`, каталог `2750`, umask `007`;
права меняются только для нужного bot-root. Token, registry и curl-конфигурация
приватны, вне media, mode `0640`, group `101`. Замените все плейсхолдеры в private
`.env` и registry. Команды выше одинаковы для обеих локалей. Local reader принимает
file_id; remote — HTTPS POST с отдельным Bearer credential. Proxy слушает loopback
`18082`, host ingress требует собственные сертификаты. Не передавайте секреты
в URL, команды или публичные журналы. Для нескольких ботов добавьте отдельный
mount на каждый root. Для отзыва credential измените registry и пересоздайте
downloads. Путь не является постоянным ID; Range/HEAD/resume отсутствуют.
