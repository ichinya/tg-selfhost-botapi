"""Explicit pinned-source gate. Never fetches/builds or contacts Telegram implicitly."""
import argparse
import json
from pathlib import Path
import re
import subprocess


def check(source, root):
    expected = json.loads((root / "image-inputs.lock.json").read_text())["inputs"]["bot_api_revision"]
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if actual != expected:
        raise ValueError("Source revision differs from pinned BOT_API_REVISION")
    actor = (source / "telegram-bot-api/WebhookActor.cpp").read_text()
    # Assert the actual production sender's conditional header emission.
    guarded = re.search(r'if\s*\(\s*!secret_token_\.empty\(\)\s*\)\s*\{\s*hc\.add_header\("X-Telegram-Bot-Api-Secret-Token",\s*secret_token_\);\s*\}', actor)
    if not guarded or actor.count('hc.add_header("X-Telegram-Bot-Api-Secret-Token"') != 1:
        raise ValueError("Expected conditional secret header emission missing")
    patch = (root / "patches/webhook-user-agent.patch").read_text()
    ua = re.search(r'^\+\s*(hc\.add_header\("User-Agent", "[^"]+"\);)', patch, re.M)[1]
    if ua not in actor:
        raise ValueError("Tracked User-Agent patch has not been applied")
    return {"revision": actual, "conditional_secret_header": True, "user_agent_patch": True,
            "sender_harness": "NOTRUN", "live_delivery": "NOTRUN"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = check(args.source.resolve(), Path(__file__).resolve().parents[1])
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        parser.exit(1, "Pinned sender source gate FAIL/NOTRUN; no delivery claim\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
