# Disposable file-contract fixture

Uses fake identities only. The mock replaces getFile, never the production
opener/reader/handler/nginx. Writer runs the candidate Bot API image as `101:101`;
reader and handler use `10001:101`, separate read-only bot submounts and bounded
resources. Named volumes and networks belong to one unique project. The fixture
never merges with live Compose files or reads checkout `.env`, `data` or `files`.

Only `mountcheck` receives privileges, to create a nested mount inside its own
mount namespace and prove NO_XDEV. Production services retain default seccomp,
dropped capabilities and no-new-privileges. Missing Docker/openat2/mount support
fails the gate; no mandatory case is converted into a successful skip.

TLS uses a disposable self-signed CA/certificate and validates it. Receipts omit
credentials, paths and raw upstream bodies. Slow-upstream test intentionally
checks the 60-second timeout. Full runtime verification belongs in Ubuntu CI.

`--state-isolation-only` validates base/base+build without requiring split storage.
On Linux it runs the state-only nginx canary fixture; on Windows its static
models remain PASS and runtime is explicitly NOTRUN (Linux required). The full
gate runs state isolation before and after opt-in, as well as mock getFile counters
on backend/proxy denials and the shipped local-reader executable.

Writer boundary: the shell fixture proves UID/Unix access only. A separate
`permissions-probe` Docker target compiles the offline C++ harness against the
resolved revision's real tdutils target. The checker verifies the TDLib gitlink,
archived source bytes and the known FileLoaderUtils create/rename calls, then
requires real 0640/2750 create/move and reader group-access evidence. Positive
getFile bytes come from that probe, not the shell writer. This covers downloaded
media semantics, not arbitrary local uploads or a Telegram session. Source drift
or missing proof fails qualification; unrun local evidence stays UNKNOWN.
