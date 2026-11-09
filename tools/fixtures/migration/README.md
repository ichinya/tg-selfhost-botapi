# Migration fixtures

All tokens, credentials, updates and receivers are synthetic. HTTP mocks bind
literal loopback addresses; fixture clients reject other hosts before connecting.
The volume Compose file has its own random project, internal network, run labels,
named data/temp volumes, no published ports and one explicitly admitted read-only
bind of `fake-bot-api.sh`. It never mounts the host journal or production data.

Run from Linux with a locally built candidate image:

```sh
python3 tools/check_migration_safety.py --require-posix
chmod +x tools/fixtures/migration/fake-bot-api.sh
python3 tools/check_migration_volumes.py --require-docker --image "$MIGRATION_FIXTURE_IMAGE"
```

Missing prerequisites, skipped POSIX cases or failed cleanup fail the required
gate. Failed cleanup retains diagnostics in `.migration-private/volume-gate.json`.
Removal requires exact resource identity, run/project labels and approved mounts;
there is no global prune or production `down -v`.

These fixtures establish mock protocol and real filesystem lifecycle behavior.
They do not establish real Telegram queues, sessions, webhook delivery or VPS health.
