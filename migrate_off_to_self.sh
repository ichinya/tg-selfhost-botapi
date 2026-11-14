#!/usr/bin/env bash
set +x
set +v
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$script_dir/tools/migration_executor.sh" ]]; then
  printf '%s\n' 'Install the complete reviewed repository; tools/migration_executor.sh is required.' >&2
  exit 4
fi
exec bash "$script_dir/tools/migration_executor.sh" "$@"
