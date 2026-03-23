#!/usr/bin/env python3
"""SessionEnd hook that deletes trivially empty sessions.

Reads hook input JSON from stdin (session_id, transcript_path).
Runs async so it never blocks session exit.
"""

import json
import os
import sys

# claude_utils is in ~/.local/bin/claude_utils (stowed from dotfiles repo)
sys.path.insert(0, os.path.expanduser("~/.local/bin"))
from claude_utils import sessions


def main():
    hook_input = json.load(sys.stdin)
    jsonl_path = hook_input.get("transcript_path", "")

    if not jsonl_path or not os.path.isfile(jsonl_path):
        return

    if sessions.is_trivially_empty(jsonl_path):
        sessions.delete(jsonl_path)


if __name__ == "__main__":
    main()
