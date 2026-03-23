"""Session file operations for Claude Code sessions."""

import json
import os
import shutil

from . import text


def delete(jsonl_path: str) -> bool:
    """Remove a session's JSONL file and its companion directory."""
    try:
        os.remove(jsonl_path)
    except OSError:
        return False
    companion = jsonl_path.rsplit(".jsonl", 1)[0]
    if os.path.isdir(companion):
        shutil.rmtree(companion, ignore_errors=True)
    return True


def rename(jsonl_path: str, session_id: str, new_name: str) -> bool:
    """Rename a session by appending custom-title + agent-name to its JSONL."""
    try:
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "custom-title", "customTitle": new_name, "sessionId": session_id}) + "\n")
            f.write(json.dumps({"type": "agent-name", "agentName": new_name, "sessionId": session_id}) + "\n")
        return True
    except OSError:
        return False


def is_trivially_empty(jsonl_path: str,
                       max_user_len: int = 100,
                       max_assistant_len: int = 200) -> bool:
    """Check if a session is trivially empty and should be auto-deleted.

    Returns True if:
      - 0 useful user messages
      - 1 useful user message with short text AND short response
    """
    useful_user_count = 0
    first_useful_user_len = 0
    first_assistant_len = 0

    with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type", "")
            if entry_type == "user":
                t = text.extract(entry)
                if text.is_useful(t):
                    useful_user_count += 1
                    if useful_user_count == 1:
                        first_useful_user_len = len(t)
            elif entry_type == "assistant":
                if first_assistant_len == 0:
                    first_assistant_len = len(text.extract(entry))

    if useful_user_count == 0:
        return True
    if (useful_user_count == 1
            and first_useful_user_len < max_user_len
            and first_assistant_len < max_assistant_len):
        return True
    return False


def load_messages(jsonl_path: str, max_messages: int = 20) -> list[dict]:
    """Read the last N user/assistant messages from a session JSONL.

    Returns list of {"role": "user"|"assistant", "text": str}.
    """
    messages = []
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                entry_type = entry.get("type", "")
                if entry_type == "user":
                    t = text.extract(entry)
                    if t and not text.is_system(t):
                        messages.append({"role": "user", "text": text.clean(t)})
                elif entry_type == "assistant":
                    t = text.extract(entry)
                    if t:
                        messages.append({"role": "assistant", "text": text.clean(t)})
    except (OSError, UnicodeDecodeError):
        pass
    return messages[-max_messages:]
