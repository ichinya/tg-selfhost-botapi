# File access examples

Linux/amd64 and a kernel supporting openat2 are required. The Bot API is a trusted
local API, not a tenant sandbox. Each application sees only its own bot subtree.
The host/writer is trusted; no nested mounts are permitted beneath that subtree.

1. Prepare an empty media directory with `sudo install -d -m 0770 -o 101 -g 101 ./media`,
   then enable split storage: `docker compose -f docker-compose.yml -f docker-compose.files.yml up -d`.
2. Call getFile on the trusted private API. Set `BOT_A_ROOT` to the exact bot
   directory in its absolute file_path and `BOT_A_HOST_ROOT` to its existing host
   backing. Verify the full suffix, including token, `:` / `~` and test-DC suffix.
   A bot numeric ID alone does not determine this directory. Never mount all data
   or the whole media parent. Do not print token-bearing paths in diagnostics.
3. Set `BOT_TOKEN_FILE` to an absolute protected regular file (owner root or UID
   101, mode 0400/0600 or 0440/0640 with group 101). Use an ACL only after checking
   actual writer modes. Consumers run as 101:101, with one read-only subtree.
4. Set `DOWNLOADS_IMAGE` to the qualified image containing the reader, then run:

```sh
docker compose -f docker-compose.yml -f docker-compose.files.yml \
  -f examples/files/compose.local.yml run --rm reader '<FILE_ID>' > downloaded.bin
```

The reader calls getFile and copies from the validated FD; a missing mount or
unsafe path fails. Percent sequences in filesystem names are literal, never URL
decoded. The opener rejects symlinks, hardlinks, device/mount crossings and special
files. A pinned FD avoids reopening a path after validation. Cache eviction can
still cause a safe failure; there is no retention guarantee.

## Remote reader

Set `DOWNLOAD_BOT_TOKEN_FILE` and `DOWNLOAD_AUTH_TOKEN_FILE` to two protected
absolute files. The latter contains an independent random 32–256 character
credential (letters, digits, `.`, `_`, `~`, `-`), never the Telegram token.
Use the same qualified `DOWNLOADS_IMAGE`, `BOT_A_ROOT`, `BOT_A_HOST_ROOT` as above.

```sh
docker compose -f docker-compose.yml -f docker-compose.files.yml \
  -f docker-compose.downloads.yml up -d
```

HTTP port 18082 binds loopback. Install `nginx.downloads.conf` in the host TLS
frontend and supply its certificate/key, then set `DOWNLOAD_URL` to
`https://downloads.example.com/v1/files/download` and run
`python examples/files/remote_client.py '<FILE_ID>' > downloaded.bin`.
The client reads auth from `DOWNLOAD_AUTH_TOKEN_FILE` or `DOWNLOAD_AUTH_TOKEN`.
The frontend has no media or bot token mounts. Do not publish the HTTP listener.

The only request body is `{"file_id":"<FILE_ID>"}`. Additional keys, query,
duplicate headers, chunked bodies and client paths are rejected. Errors: 401 auth;
400 malformed; 413 body over 4 KiB; 415 content type; 405 methods/HEAD; 416 Range;
404 missing/foreign/unsafe file; 502 upstream; 504 upstream timeout; 503 overload.
Responses are no-store attachments, streamed in blocks of at most 64 KiB, with
four active requests by default (`DOWNLOAD_WORKERS`, 1–32). Client timeout is 30s;
`DOWNLOAD_MAX_DURATION` sets the total deadline (600s default, 1–3600s).
Range, resume and retention SLA are not supported. Rotate auth by replacing the
protected secret file and restarting the handler; the old credential stops working.

The client requires one Content-Length and rejects truncation. Discard partial
stdout/output files whenever it exits nonzero. Path/URL-like file IDs are rejected
before any getFile request. A local image can also be built with the downloads
Compose service's `build:` configuration; qualification is still required.
