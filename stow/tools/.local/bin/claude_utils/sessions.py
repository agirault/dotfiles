"""Session file operations for Claude Code sessions."""

import json
import os
import shutil
import subprocess
import sys

from . import text

AUTO_NAME_TIMEOUT = 20


def _iter_entries(jsonl_path):
    """Yield parsed JSON entries from a session JSONL file."""
    with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue


# -- File operations --


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


# -- Session analysis --


def has_custom_title(jsonl_path: str) -> bool:
    """Check if the session already has a custom-title entry."""
    for entry in _iter_entries(jsonl_path):
        if entry.get("type") == "custom-title":
            return True
    return False


def get_user_messages(jsonl_path: str, max_messages: int = 3) -> list[str]:
    """Extract first N useful user messages (cleaned text)."""
    messages = []
    for entry in _iter_entries(jsonl_path):
        if entry.get("type") != "user":
            continue
        t = text.extract(entry)
        if t and text.is_useful(t):
            messages.append(text.clean(t))
            if len(messages) >= max_messages:
                break
    return messages


def get_conversation_context(jsonl_path: str, max_messages: int = 200) -> list[dict]:
    """Extract all conversation messages for naming context.

    Returns list of {"role": "user"|"assistant", "text": str}, skipping
    system content, trivial messages, and short boilerplate responses.
    """
    messages = []
    for entry in _iter_entries(jsonl_path):
        entry_type = entry.get("type", "")
        if entry_type == "user":
            t = text.extract(entry)
            if t and text.is_useful(t):
                messages.append({"role": "user", "text": text.clean(t)})
        elif entry_type == "assistant":
            t = text.extract(entry)
            if t and not text.is_system(t):
                cleaned = text.clean(t)
                if len(cleaned) > 30:
                    messages.append({"role": "assistant", "text": cleaned})
        if len(messages) >= max_messages:
            break
    return messages


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

    for entry in _iter_entries(jsonl_path):
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
        for entry in _iter_entries(jsonl_path):
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


# -- Auto-naming --


def generate_title(jsonl_path: str) -> str | None:
    """Generate a session title using Claude haiku from conversation context.

    Returns a 3-5 word title string, or None on failure.
    """
    conversation = get_conversation_context(jsonl_path)
    if not conversation:
        return None

    lines = []
    for msg in conversation:
        role = "User" if msg["role"] == "user" else "Claude"
        lines.append(f"{role}: {msg['text'][:300]}")
    context = "\n".join(lines)

    prompt = (
        "Below is a coding session. "
        "Generate a short title (3-6 words) that captures what was worked on. "
        "If multiple topics were covered, join them with &. "
        "Output ONLY the title. No quotes, no punctuation at the end.\n\n"
        f"{context}"
    )
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "haiku", "--no-session-persistence", prompt],
            capture_output=True, text=True, timeout=AUTO_NAME_TIMEOUT,
        )
        if result.returncode == 0 and result.stdout.strip():
            title = result.stdout.strip()
            if 1 < len(title) < 60:
                return title
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def auto_name(jsonl_path: str, session_id: str) -> str | None:
    """Generate and apply an auto-title to a session.

    Returns the new title, or None if generation failed or was skipped.
    Can be called from hooks (unnamed sessions) or UI (on demand).
    """
    title = generate_title(jsonl_path)
    if title and rename(jsonl_path, session_id, title):
        return title
    return None
