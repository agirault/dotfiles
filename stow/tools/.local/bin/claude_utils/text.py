"""Text extraction and filtering for Claude Code session JSONL entries."""

import re

_XML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

SYSTEM_PREFIXES = (
    "<local-command-caveat>",
    "<local-command-stdout>",
    "<command-message>",
    "<command-name>",
    "[Request interrupted by user",
)

TRIVIAL_MESSAGES = frozenset(("", "/exit", "exit", "hi", "hello", "/clear"))


def clean(text: str) -> str:
    """Strip XML tags and collapse whitespace."""
    return _WHITESPACE_RE.sub(" ", _XML_TAG_RE.sub("", text)).strip()


def is_system(text: str) -> bool:
    """Check if text is a system-injected message (not real user input)."""
    return text.startswith(SYSTEM_PREFIXES)


def is_useful(text: str) -> bool:
    """Check if text is a non-trivial, non-system user message."""
    if not text or is_system(text):
        return False
    return clean(text).lower() not in TRIVIAL_MESSAGES


def extract(entry: dict) -> str:
    """Extract first non-empty text from a user or assistant message entry.

    Checks entry.content (str or list of content blocks), then falls through
    to entry.message.content for the nested format Claude sometimes uses.
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
