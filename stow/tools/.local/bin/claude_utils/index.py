#!/usr/bin/env python3
"""Index all Claude Code sessions across all project directories.

Scans ~/.claude/projects/*/*.jsonl and outputs a JSON array with metadata
per session: title, message count, last active time, git branch, size, etc.
"""

import json
import os
import sys
from datetime import datetime, timezone
from glob import glob

from . import text
from .schema import Session

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")


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

    title_info = {"custom": None, "named": False}
    user = {"first": "", "last": "", "count": 0}
    assistant = {"first": "", "last": "", "count": 0}
    last_timestamp = None
    git_branch = None

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

                if entry_type == "custom-title":
                    title_info["custom"] = entry.get("customTitle", "")
                    title_info["named"] = True
                    continue

                if entry_type not in ("user", "assistant"):
                    continue

                # Common fields for both user and assistant
                ts = entry.get("timestamp")
                if ts:
                    last_timestamp = ts
                branch = entry.get("gitBranch")
                if branch:
                    git_branch = branch

                bucket = user if entry_type == "user" else assistant
                bucket["count"] += 1

                t = text.extract(entry)
                if not t or text.is_system(t):
                    continue

                cleaned = text.clean(t)
                if not bucket["first"]:
                    bucket["first"] = cleaned
                bucket["last"] = cleaned

    except (OSError, UnicodeDecodeError):
        return None

    # Determine title
    if title_info["custom"]:
        title = title_info["custom"]
    elif user["first"]:
        title = user["first"][:50] + ("..." if len(user["first"]) > 50 else "")
    else:
        title = "(empty)"

    session_id = os.path.splitext(os.path.basename(jsonl_path))[0]
    msg_count = user["count"] + assistant["count"]

    return Session(
        session_id=session_id,
        jsonl_path=jsonl_path,
        dir="",  # filled in by caller
        title=title,
        named=title_info["named"],
        message_count=msg_count,
        user_msg_count=user["count"],
        assistant_msg_count=assistant["count"],
        last_active=last_timestamp or "",
        relative_time=relative_time(last_timestamp) if last_timestamp else "unknown",
        git_branch=git_branch or "",
        size=human_size(file_size),
        size_bytes=file_size,
        first_user_msg=user["first"][:100],
        first_assistant_msg=assistant["first"][:200],
        last_user_msg=user["last"][:200],
        last_assistant_msg=assistant["last"][:300],
    )


def index_all_sessions() -> list[Session]:
    """Scan all Claude project directories and return session metadata."""
    if not os.path.isdir(PROJECTS_DIR):
        return []

    sessions = []
    for project_dir in sorted(glob(os.path.join(PROJECTS_DIR, "*"))):
        if not os.path.isdir(project_dir):
            continue
        decoded_dir = decode_dir_name(os.path.basename(project_dir))

        for jsonl_path in glob(os.path.join(project_dir, "*.jsonl")):
            session = index_session(jsonl_path)
            if session is not None:
                session.dir = decoded_dir
                sessions.append(session)

    sessions.sort(key=lambda s: s.last_active, reverse=True)
    return sessions


if __name__ == "__main__":
    import json as _json
    _json.dump([s.to_dict() for s in index_all_sessions()], sys.stdout, indent=2)
