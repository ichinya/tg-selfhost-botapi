#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python="${MIGRATION_PYTHON:-python3}"
if ! command -v "$python" >/dev/null 2>&1 || ! "$python" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 4)'; then
  printf '%s\n' '{"reason":"python_3_11_required","exit_code":4}'
  exit 4
fi
case "${1:-}" in
  plan|apply|status|resume|reconcile|export)
    exec "$python" "$script_dir/tools/migration_cli.py" "$@"
    ;;
esac
# Refuse positional credentials without echoing or forwarding their values.
if [[ $# -gt 0 && "$1" != --* ]]; then
  printf '%s\n' '{"reason":"use_subcommands_and_BOT_TOKEN_or_BOT_TOKEN_FILE","exit_code":4}'
  exit 4
fi
export SELF_BOT_URL="${SELF_BOT_URL:-${TELEGRAM_BOT_URL:-}}"
export WEBHOOK_URL="${WEBHOOK_URL:-${WEB_HOOK:-}}"
exec "$python" "$script_dir/tools/migration_cli.py" legacy "$@"
