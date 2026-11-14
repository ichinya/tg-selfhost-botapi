"""Validate documented Compose combinations without building or starting containers."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'docker-compose.yml'
COMBINATIONS = [
    (), ('docker-compose.build.yml',),
    ('docker-compose.observability.yml',),
    ('docker-compose.build.yml', 'docker-compose.observability.yml', 'docker-compose.observability.build.yml'),
    ('docker-compose.secrets.yml',),
    ('docker-compose.secrets.yml', 'docker-compose.observability.yml'),
    ('docker-compose.nonroot.yml',), ('docker-compose.files.yml',),
    ('docker-compose.nonroot.yml', 'docker-compose.files.yml'),
    ('docker-compose.files.yml', 'docker-compose.downloads.yml'),
    ('docker-compose.files.yml', 'examples/files/compose.local.yml'),
]

def main():
    env = os.environ.copy()
    env.update(DOWNLOADS_IMAGE='downloads-candidate:check', BOTAPI_UID='101', BOTAPI_GID='101', BOTAPI_STATE_SOURCE='/tmp/state', BOTAPI_TEMP_SOURCE='/tmp/temp', BOTAPI_MEDIA_SOURCE='/tmp/media', API_ID='12345', API_HASH='test-placeholder',
               TELEGRAM_API_ID_SECRET_PATH='/tmp/example-id', TELEGRAM_API_HASH_SECRET_PATH='/tmp/example-hash',
               BOT_A_ROOT='/var/lib/telegram-bot-api-files/12345:SYNTHETIC_A',
               BOT_A_HOST_ROOT='/tmp/isolated-media/bot-a', BOT_TOKEN_FILE='/tmp/example-token',
               DOWNLOAD_BOT_TOKEN_FILE='/tmp/example-token', DOWNLOAD_AUTH_TOKEN_FILE='/tmp/example-auth')
    for overlays in COMBINATIONS:
        cmd = ['docker', 'compose', '--env-file', str(ROOT / '.env.example')]
        for name in (BASE, *overlays):
            cmd.extend(('-f', str(ROOT / name)))
        subprocess.run([*cmd, 'config', '--quiet'], cwd=ROOT, env=env, check=True)
        print('PASS:', ' + '.join((BASE, *overlays)))

if __name__ == '__main__':
    main()
