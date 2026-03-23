#!/usr/bin/env python3
"""SessionEnd hook that auto-names unnamed sessions using Claude haiku.

Skips sessions that already have a title, were deleted by cleanup, or
have <= 1 useful user message. On failure, does nothing.

Reads hook input JSON from stdin. Runs async so it never blocks exit.
"""

import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/.local/bin"))
from claude_utils import sessions


def main():
    hook_input = json.load(sys.stdin)
    jsonl_path = hook_input.get("transcript_path", "")
    session_id = hook_input.get("session_id", "")

    if not jsonl_path or not os.path.isfile(jsonl_path):
        return

    if sessions.has_custom_title(jsonl_path):
        return

    if len(sessions.get_user_messages(jsonl_path)) <= 1:
        return

    sessions.auto_name(jsonl_path, session_id)


if __name__ == "__main__":
    main()
