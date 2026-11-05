"""Platform selection shared by issue #10 subprocess tests (no WSL fallback)."""
import os
from pathlib import Path
import shutil


def posix_path(path):
    path = Path(path).resolve().as_posix()
    if os.name == 'nt' and len(path) >= 3 and path[1:3] == ':/':
        return '/' + path[0].lower() + path[2:]
    return path


def bash_binary():
    configured = os.environ.get('ISSUE10_BASH')
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute():
            raise RuntimeError('ISSUE10_BASH must be an absolute path')
    elif os.name == 'nt':
        candidate = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git/bin/bash.exe'
    else:
        candidate = Path(shutil.which('bash') or '/missing/bash')
    normalized = candidate.as_posix().lower()
    if normalized.endswith('/wsl.exe') or '/windows/system32/' in normalized or '/windows/sysnative/' in normalized:
        raise RuntimeError('WSL launchers are not supported; set ISSUE10_BASH to Git Bash')
    if not candidate.is_file():
        raise RuntimeError('Bash is required; set ISSUE10_BASH to its full path')
    return str(candidate)
