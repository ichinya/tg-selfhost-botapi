"""Fail closed when the reviewed upstream statistics source changes."""
import hashlib
from pathlib import Path
import sys

EXPECTED = (
    '01cf82e3f825ab62e5cea2403b6f671446199c1b3f72f6dd1eeb5735a725f1cd',
    'a90eb79e23d45f8f06e5a9c7fd80cfa674566830af72c93ddaeaa51d134bedc2',
    'df158f03f4cccaa47ca67aae0392708a4474909b8c155c3ffc94d25ba8e72250',
)


def check(root):
    manager = (root / 'telegram-bot-api/ClientManager.cpp').read_text(encoding='utf-8')
    stats = (root / 'telegram-bot-api/Stats.cpp').read_text(encoding='utf-8')
    header = (root / 'telegram-bot-api/Stats.h').read_text(encoding='utf-8')
    start = stats.index('td::string BotStatActor::get_description()')
    fragments = (manager[manager.index('void ClientManager::get_stats('):manager.index('td::int64 ClientManager::get_tqueue_id(')],
                 stats[start:start + 300], header[header.index('class BotStatActor final'):])
    return tuple(hashlib.sha256(fragment.encode('utf-8')).hexdigest() for fragment in fragments) == EXPECTED


if __name__ == '__main__':
    try: ok = len(sys.argv) == 2 and check(Path(sys.argv[1]))
    except (OSError, ValueError, UnicodeError): ok = False
    if not ok: print('stats_source_review_required', file=sys.stderr)
    raise SystemExit(0 if ok else 1)
