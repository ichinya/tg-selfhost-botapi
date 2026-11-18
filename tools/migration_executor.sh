#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python="${MIGRATION_PYTHON:-python3}"

# =========================
# Executor adapter: subcommands and --option calls are reviewed by the CLI.
# =========================

cli() {
  if ! command -v "$python" >/dev/null 2>&1 || ! "$python" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 4)'; then
    printf '%s\n' '{"reason":"python_3_11_required","exit_code":4}'
    exit 4
  fi
  exec "$python" "$script_dir/migration_cli.py" "$@"
}

case "${1:-}" in
  plan|apply|status|resume|reconcile|export)
    cli "$@"
    ;;
esac

export SELF_BOT_URL="${SELF_BOT_URL:-${TELEGRAM_BOT_URL:-}}"
export WEBHOOK_URL="${WEBHOOK_URL:-${WEB_HOOK:-}}"
cli legacy "$@"
