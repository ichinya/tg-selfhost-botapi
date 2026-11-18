#!/usr/bin/env python3
"""Run inside the reader container. Only file_id is accepted from the caller."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.file_access import FileAccessError
from tools.file_contract import Binding, ContractError, local_copy, read_private_file


def main():
    if len(sys.argv) != 2:
        raise ContractError('one file_id required')
    # Operator-provided paths and secrets, never caller input.
    token_data, _ = read_private_file(os.environ['BOT_TOKEN_FILE'], 256)
    token = token_data.decode('utf-8').strip()
    for name, default in (('BOT_TEST_DC', 'false'), ('BOT_COLON_LAYOUT', 'true')):
        if os.environ.get(name, default) not in ('true', 'false'):
            raise ContractError('invalid private configuration')
    binding = Binding(token, os.environ['BOTAPI_ENDPOINT'], os.environ['BOT_MEDIA_ROOT'],
                      os.environ['BOT_ROOT'], test_dc=os.environ.get('BOT_TEST_DC', 'false') == 'true',
                      colon=os.environ.get('BOT_COLON_LAYOUT', 'true') == 'true')
    local_copy(binding, sys.argv[1], sys.stdout.buffer)


if __name__ == '__main__':
    try:
        main()
    except (OSError, KeyError, ValueError, FileAccessError, ContractError):
        print('file unavailable', file=sys.stderr)
        sys.exit(1)
