# Приёмка аудита

Candidate base: `f490df7562bd4f054066d5b0a5a8bfbefa6bdff5` (merged PR #44).

Закрытие issue учитывается отдельно от технической приёмки. Runtime/live результаты остаются NOTRUN до получения receipts точного candidate.

| Issue | GitHub | Owner | Verification | Result |
| --- | --- | --- | --- | --- |
| [#1](https://github.com/ichinya/tg-selfhost-botapi/issues/1) | open | T15/T19 | `VPS runbook` | NOTRUN |
| [#2](https://github.com/ichinya/tg-selfhost-botapi/issues/2) | open | T7/T8/T10 | `test_migration_faults` | NOTRUN |
| [#3](https://github.com/ichinya/tg-selfhost-botapi/issues/3) | open | T2 | `check_file_contract` | NOTRUN |
| [#4](https://github.com/ichinya/tg-selfhost-botapi/issues/4) | closed | T4 | `check_gateway_uploads` | NOTRUN |
| [#5](https://github.com/ichinya/tg-selfhost-botapi/issues/5) | closed | T5 | `check_file_contract` | NOTRUN |
| [#6](https://github.com/ichinya/tg-selfhost-botapi/issues/6) | closed | T9 | `test_migration_ui.mjs` | NOTRUN |
| [#7](https://github.com/ichinya/tg-selfhost-botapi/issues/7) | closed | T6 | `test_webhook_profile_contract` | NOTRUN |
| [#8](https://github.com/ichinya/tg-selfhost-botapi/issues/8) | closed | T3 | `test_issue8_shell_safety` | NOTRUN |
| [#9](https://github.com/ichinya/tg-selfhost-botapi/issues/9) | open | T6/T8/T9 | `test_migration_contract` | NOTRUN |
| [#10](https://github.com/ichinya/tg-selfhost-botapi/issues/10) | closed | T15 | `test_issue10_examples` | NOTRUN |
| [#11](https://github.com/ichinya/tg-selfhost-botapi/issues/11) | closed | T7 | `test_migration_http` | NOTRUN |
| [#12](https://github.com/ichinya/tg-selfhost-botapi/issues/12) | open | T12/T14 | `image qualification` | NOTRUN |
| [#13](https://github.com/ichinya/tg-selfhost-botapi/issues/13) | closed | T16 | `test_doctor` | NOTRUN |
| [#14](https://github.com/ichinya/tg-selfhost-botapi/issues/14) | closed | T8/T9/T10 | `test_migration_interfaces` | NOTRUN |
| [#15](https://github.com/ichinya/tg-selfhost-botapi/issues/15) | open | T17 | `profile integration` | NOTRUN |
| [#16](https://github.com/ichinya/tg-selfhost-botapi/issues/16) | closed | T18 | `check_observability` | NOTRUN |
| [#17](https://github.com/ichinya/tg-selfhost-botapi/issues/17) | closed | T11 | `issue17_security_gate` | NOTRUN |
| [#18](https://github.com/ichinya/tg-selfhost-botapi/issues/18) | open | T19 | `clean candidate gates` | NOTRUN |
| [#21](https://github.com/ichinya/tg-selfhost-botapi/issues/21) | closed | T14 | `check_nonroot` | NOTRUN |
| [#22](https://github.com/ichinya/tg-selfhost-botapi/issues/22) | open | T13 | `native image qualification` | NOTRUN |
| [#23](https://github.com/ichinya/tg-selfhost-botapi/issues/23) | open | T12 | `test_image_inputs` | NOTRUN |

Политика интеграции

PR #37/#38/#42 конфликтуют с базой. Их native runners, APK policy и release/restore контракты рассматриваются для rebase-adopt в T12–T14 после чтения кода; параллельные publisher/restore механизмы не допускаются. Непроверенный WIP исключён, включая чужой observability build override. Candidate использует tracked overrides PR #44.

Полная инвентаризация: `tools/fixtures/issue19-admission.json`. Соседний #1 остаётся docs-only; #15 использует tracked examples/files до сверки T17; #2/#9 используют единый Python executor. Чужие исходные файлы не перезаписываются.
