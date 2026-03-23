#!/usr/bin/env python3
"""Index all Claude Code sessions across all project directories.

Scans ~/.claude/projects/*/*.jsonl and outputs a JSON array with metadata
per session: title, message count, last active time, git branch, size, etc.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from glob import glob

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")

_XML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_TRIVIAL_MESSAGES = frozenset(("", "/exit", "exit", "hi", "hello", "/clear"))


# -- Path decoding --


def decode_dir_name(encoded: str) -> str:
    """Decode a Claude project directory name back to a real path.

    Claude encodes paths by replacing '/' with '-', but directory names can
    also contain '-'. We resolve ambiguity by checking which paths exist on
    disk, greedily matching the longest existing prefix at each level.
    """
    home = os.path.expanduser("~")
    home_encoded = home.replace("/", "-")

    if encoded.startswith(home_encoded):
        rest = encoded[len(home_encoded) :]
        if not rest:
            return "~"
        resolved = _resolve_path(home, rest[1:].split("-"))
        return "~" + resolved[len(home) :]

    parts = encoded.lstrip("-").split("-")
    return _resolve_path("/", parts)


def _resolve_path(base: str, parts: list[str]) -> str:
    """Greedily resolve dash-separated parts into a real path.

    Tries joining as many consecutive parts as possible with '-' to form a
    directory name that exists on disk. Falls back to treating each part as
    a separate path component.
    """
    if not parts:
        return base
    for end in range(len(parts), 0, -1):
        candidate = os.path.join(base, "-".join(parts[:end]))
        if os.path.isdir(candidate):
            return _resolve_path(candidate, parts[end:])
    return _resolve_path(os.path.join(base, parts[0]), parts[1:])


# -- Text helpers --


def _clean_text(text: str) -> str:
    """Strip XML tags and collapse whitespace."""
    return _WHITESPACE_RE.sub(" ", _XML_TAG_RE.sub("", text)).strip()


def _is_system_content(text: str) -> bool:
    """Check if text is a system-injected message (not real user input)."""
    return text.startswith(("<local-command-caveat>", "<command-message>"))


def _is_useful_message(text: str) -> bool:
    """Check if text is a non-trivial, non-system user message."""
    if not text or _is_system_content(text):
        return False
    return _clean_text(text).lower() not in _TRIVIAL_MESSAGES


def _extract_text(entry: dict) -> str:
    """Extract first non-empty text from a message entry.

    Checks entry.content (str or list of content blocks), then falls through
    to entry.message.content for the nested format Claude sometimes uses.
    Returns "" only if no text is found anywhere.
    """
    for source in (entry, entry.get("message") or {}):
        content = source.get("content")
        if isinstance(content, str) and content:
            return content
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                    return item["text"]
    return ""


# -- Formatting --


def relative_time(iso_timestamp: str) -> str:
    """Convert ISO timestamp to human-readable relative time."""
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - dt
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        days = seconds // 86400
        if days < 30:
            return f"{days}d ago"
        if days < 365:
            return f"{days // 30}mo ago"
        return f"{days // 365}y ago"
    except (ValueError, TypeError):
        return "unknown"


def human_size(size_bytes: int) -> str:
    """Convert bytes to human-readable size."""
    for unit in ("B", "K", "M", "G"):
        if size_bytes < 1024:
            return f"{size_bytes}{unit}" if unit == "B" else f"{size_bytes:.0f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.0f}T"


# -- Session indexing --


def index_session(jsonl_path: str) -> dict | None:
    """Extract metadata from a single session JSONL file."""
    try:
        file_size = os.path.getsize(jsonl_path)
    except OSError:
        return None

    custom_title = None
    named = False
    first_user_msg = ""
    first_assistant_msg = ""
    last_timestamp = None
    git_branch = None
    user_msg_count = 0
    assistant_msg_count = 0

    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type", "")

                if entry_type == "custom-title":
                    custom_title = entry.get("customTitle", "")
                    named = True

                elif entry_type == "user":
                    user_msg_count += 1
                    ts = entry.get("timestamp")
                    if ts:
                        last_timestamp = ts
                    branch = entry.get("gitBranch")
                    if branch:
                        git_branch = branch
                    if not first_user_msg:
                        text = _extract_text(entry)
                        if _is_useful_message(text):
                            first_user_msg = _clean_text(text)

                elif entry_type == "assistant":
                    assistant_msg_count += 1
                    ts = entry.get("timestamp")
                    if ts:
                        last_timestamp = ts
                    branch = entry.get("gitBranch")
                    if branch:
                        git_branch = branch
                    if not first_assistant_msg:
                        text = _extract_text(entry)
                        if text:
                            first_assistant_msg = _clean_text(text)

    except (OSError, UnicodeDecodeError):
        return None

    # Determine title
    if custom_title:
        title = custom_title
    elif first_user_msg:
        title = first_user_msg[:50]
        if len(first_user_msg) > 50:
            title += "..."
    else:
        title = "(untitled)"

    session_id = os.path.splitext(os.path.basename(jsonl_path))[0]

    return {
        "session_id": session_id,
        "jsonl_path": jsonl_path,
        "dir": "",  # filled in by caller
        "title": title,
        "named": named,
        "message_count": user_msg_count + assistant_msg_count,
        "user_msg_count": user_msg_count,
        "assistant_msg_count": assistant_msg_count,
        "last_active": last_timestamp or "",
        "relative_time": relative_time(last_timestamp) if last_timestamp else "unknown",
        "git_branch": git_branch or "",
        "size": human_size(file_size),
        "size_bytes": file_size,
        "first_user_msg": first_user_msg[:100],
        "first_assistant_msg": first_assistant_msg[:200],
    }


def main():
    if not os.path.isdir(PROJECTS_DIR):
        json.dump([], sys.stdout)
        return

    sessions = []
    for project_dir in sorted(glob(os.path.join(PROJECTS_DIR, "*"))):
        if not os.path.isdir(project_dir):
            continue
        decoded_dir = decode_dir_name(os.path.basename(project_dir))

        for jsonl_path in glob(os.path.join(project_dir, "*.jsonl")):
            session = index_session(jsonl_path)
            if session is not None:
                session["dir"] = decoded_dir
                sessions.append(session)

    sessions.sort(key=lambda s: s.get("last_active", ""), reverse=True)
    json.dump(sessions, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
