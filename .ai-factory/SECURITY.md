# Accepted security risks

These inherited risks remain present; acceptance does not mitigate them. Remove each exception when its listed remediation is merged.

## SEC-01

- id: SEC-01
- severity: HIGH
- file: nginx.conf
- accepted: 2026-11-06
- owner: #3 (P0, OPEN) and #5 (P1, OPEN)
- reason: Inherited from main; unauthenticated /file/ access exposes the Bot API state directory. Remediation is outside issue #21.
- removal condition: Merge the remediations for #3 and #5.

## SEC-02

- id: SEC-02
- severity: HIGH
- file: tg_selfhost_botapi_migrator.html
- accepted: 2026-11-06
- owner: #8 (P1, OPEN)
- reason: Inherited from main; unescaped URLs in generated shell commands can cause shell injection. Remediation is outside issue #21.
- removal condition: Merge the remediation for #8.
