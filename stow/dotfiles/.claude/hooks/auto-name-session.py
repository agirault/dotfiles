#!/usr/bin/env python3
"""Stop hook that auto-names unnamed sessions using Claude haiku.

Fires after every assistant turn. Skips sessions that already have a title
or have <= 1 useful user message. A sibling lockfile held via flock prevents
concurrent runs (e.g. rapid back-to-back stops) from appending duplicate
titles; the kernel releases the lock on process exit so a crash can't wedge
naming.

Reads hook input JSON from stdin. Runs async so it never blocks.
"""

import fcntl
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

    with open(jsonl_path + ".naming.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        sessions.auto_name(jsonl_path, session_id)


if __name__ == "__main__":
    main()
