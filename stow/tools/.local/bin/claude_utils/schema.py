"""Data models for Claude Code session management."""

from dataclasses import dataclass, asdict


@dataclass
class Session:
    """Metadata for a single Claude Code session."""
    session_id: str
    jsonl_path: str
    dir: str
    title: str
    named: bool
    message_count: int
    user_msg_count: int
    assistant_msg_count: int
    last_active: str
    relative_time: str
    git_branch: str
    size: str
    size_bytes: int
    first_user_msg: str
    first_assistant_msg: str
    last_user_msg: str
    last_assistant_msg: str

    def to_dict(self) -> dict:
        return asdict(self)
