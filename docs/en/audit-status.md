---
title: Audit acceptance
translation: /docs/ru/audit-status.html
---

# Audit acceptance

Candidate base: `f490df7562bd4f054066d5b0a5a8bfbefa6bdff5` (merged PR #44).

Issue closure is distinct from technical acceptance. All runtime/live results below remain NOTRUN until exact-candidate receipts exist.

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

Integration policy

PR #37/#38/#42 are conflicting candidates. Rebase-adopt their native runner, APK policy and release/restore contracts in T12–T14 after source review; no parallel publisher or restore authority. Unreviewed WIP is excluded, including the foreign observability build override. The candidate uses PR #44 tracked overrides.

Full file inventory: `tools/fixtures/issue19-admission.json`. Sibling #1 remains docs-only; #15 uses existing tracked examples/files pending T17 review; #2/#9 use the canonical Python authority. No source WIP is overwritten.

### Execution slice
All T1–T19 source slices are prepared as ordered patches against f490df7. Git metadata is read-only in this session, so no task commit exists. Runtime/live acceptance is NOTRUN: verification deferred to CI/gates. Partial boundaries: T10 does not collect state-transfer/delivery/effect or source-secret audits; T16 retains the existing doctor checks and documents new unobserved provider/native facts. Issue #19 must remain open pending committed-candidate and external acceptance.

Local source verification: 418 discovered tests, 368 PASS / 50 SKIP; 8 filesystem tests explicitly deferred after access denial. Later affected image/provider (52 tests) and doctor (71 tests, 1 skip) suites passed; JS client 5 PASS. These suites overlap. See tools/fixtures/issue19-local-verification.json. No image, native, browser, POSIX, restore or live acceptance is claimed.
