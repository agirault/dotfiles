#!/usr/bin/env python3
"""Persistent Claude Code review helper."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


DEFAULT_PROMPT = (
    "Review the supplied changes for correctness bugs, regressions, security "
    "issues, and meaningful missing tests. Findings only, ordered by severity. "
    "Cite paths and diff context. Avoid style-only comments. If there are no "
    "findings, say so and mention residual risk."
)

CHILD_SYSTEM_PROMPT = (
    "You are a nested Claude Code review subprocess. Review only the provided "
    "prompt, diff context, and explicit file paths. Do not invoke Claude Code, "
    "slash commands, skills, write tools, shell commands, or external agents. "
    "Do not edit files. Return concise, actionable findings. Do not claim spec "
    "compliance unless explicit requirements are supplied."
)

MODE_SYSTEM_PROMPTS = {
    "implementation": (
        "Review as a clear implementation reviewer. Prioritize correctness bugs, "
        "regressions, edge cases, error handling, compatibility, security issues, "
        "and meaningful missing tests. Avoid speculative product critique."
    ),
    "adversarial": (
        "Review as a skeptical architecture and design reviewer. Challenge design "
        "assumptions, invariants, boundaries, data ownership, failure modes, "
        "migration risks, operational risks, and rollback paths. Only report risks "
        "that could plausibly change the design or implementation."
    ),
}

REQUIREMENTS_SYSTEM_PROMPT = (
    "Compare the implementation against the supplied requirements. Identify "
    "missing acceptance criteria, wrong semantics, scope drift, and contract "
    "mismatches. Do not infer unstated requirements."
)

READ_ONLY_TOOLS = "Read,Grep,Glob,LS"
STREAM_METADATA_INTERVAL_SECONDS = 1.0

CALLER_PREFIX_ENV = (
    "CLAUDE_SESSION_NAME",
    "CLAUDE_CODE_SESSION_NAME",
    "CODEX_SESSION_NAME",
    "CODEX_THREAD_ID",
    "CLAUDE_SESSION_ID",
)

TERMINAL_STATUSES = {"done", "failed", "timeout", "crashed", "cancelled"}


@dataclass(frozen=True)
class ReviewPaths:
    metadata: Path
    findings: Path
    stdout_log: Path
    stderr_log: Path
    stream_log: Path
    request: Path


@dataclass(frozen=True)
class ReviewRunResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class StreamMetadataState:
    event_count: int = 0
    last_metadata_update_at: float = 0.0
    last_partial_text_at: str | None = None


def epoch_seconds() -> float:
    return time.time()


def iso_from_epoch(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def iso_now() -> str:
    return iso_from_epoch(epoch_seconds())


def epoch_from_iso(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        if Path(f"/proc/{pid}").exists():
            return True
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-o", "pid="],
            text=True,
            capture_output=True,
            check=False,
        )
        return proc.returncode == 0 and proc.stdout.strip() == str(pid)
    except PermissionError:
        return True
    return True


def run(
    args: list[str],
    cwd: Path,
    *,
    input_text: str | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            cwd=str(cwd),
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        message = f"command timed out after {timeout} seconds"
        stderr = f"{stderr}\n{message}".strip()
        return subprocess.CompletedProcess(args, 124, stdout, stderr)


def git_output(cwd: Path, args: list[str], timeout: float | None = 30) -> str:
    proc = run(["git", *args], cwd, timeout=timeout)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def repo_identity(cwd: Path) -> tuple[str, str, str]:
    root = git_output(cwd, ["rev-parse", "--show-toplevel"])
    if not root:
        digest = hashlib.sha1(str(cwd).encode("utf-8")).hexdigest()[:8]
        return cwd.name or "cwd", "nogit", digest

    root_path = Path(root)
    branch = git_output(cwd, ["branch", "--show-current"])
    if not branch:
        branch = git_output(cwd, ["rev-parse", "--short", "HEAD"]) or "detached"
    digest = hashlib.sha1(root.encode("utf-8")).hexdigest()[:8]
    return root_path.name, branch, digest


def safe_key(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "default"


def review_paths(store_dir: Path, key: str) -> ReviewPaths:
    safe = safe_key(key)
    store_dir = store_dir.expanduser()
    return ReviewPaths(
        metadata=store_dir / f"{safe}.json",
        findings=store_dir / f"{safe}.findings.md",
        stdout_log=store_dir / f"{safe}.stdout.log",
        stderr_log=store_dir / f"{safe}.stderr.log",
        stream_log=store_dir / f"{safe}.stream.jsonl",
        request=store_dir / f"{safe}.request.json",
    )


def default_key(cwd: Path) -> str:
    repo, branch, digest = repo_identity(cwd)
    return safe_key(f"{repo}-{branch}-{digest}")


def caller_prefix(args: argparse.Namespace) -> str | None:
    if args.no_session_name_prefix:
        return None
    if args.session_name_prefix:
        return safe_key(args.session_name_prefix)

    for name in CALLER_PREFIX_ENV:
        value = os.environ.get(name)
        if not value:
            continue
        if name == "CODEX_THREAD_ID":
            return safe_key(f"codex-{value[:8]}")
        if name == "CLAUDE_SESSION_ID":
            return safe_key(f"claude-{value[:8]}")
        return safe_key(value)
    return None


def review_session_name(args: argparse.Namespace, key: str) -> str:
    base = f"review-{safe_key(key)}"
    prefix = caller_prefix(args)
    name = f"{prefix}-{base}" if prefix else base
    if len(name) <= 120:
        return name.rstrip("-")
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return f"{name[:111].rstrip('-')}-{digest}"


def tmux_window_name(key: str, round_index: int | None = None) -> str:
    suffix = f"-r{round_index}" if round_index is not None else ""
    base = f"review-{safe_key(key)}"
    max_base_len = max(1, 80 - len(suffix))
    return f"{base[:max_base_len].rstrip('-')}{suffix}"


def resolve_background_launcher(requested: str) -> str:
    if requested == "auto":
        return "tmux" if shutil.which("tmux") else "subprocess"
    return requested


def tmux_base_cmd(socket_name: str | None) -> list[str]:
    if socket_name:
        return ["tmux", "-L", socket_name]
    return ["tmux"]


def shell_join(args: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in args)


def logfmt_value(value: Any) -> str:
    if value is None:
        return "null"
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_./:@%+=,-]+", text):
        return text
    return json.dumps(text)


def append_manager_log(path: Path, event: str, **fields: Any) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = [iso_now(), f"event={logfmt_value(event)}"]
    parts.extend(f"{name}={logfmt_value(value)}" for name, value in sorted(fields.items()))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(" ".join(parts) + "\n")


def tmux_manager_log_path(store_dir: Path, session_name: str) -> Path:
    return store_dir.expanduser() / f"{safe_key(session_name)}.manager.log"


def tmux_manager_command(manager_log: Path) -> str:
    manager_log = manager_log.expanduser()
    script = (
        "mkdir -p "
        + shlex.quote(str(manager_log.parent))
        + "; touch "
        + shlex.quote(str(manager_log))
        + "; printf '%s\\n' 'Claude review manager. Active review jobs use separate windows.'; "
        + "printf '%s\\n' "
        + shlex.quote(f"Manager log: {manager_log}")
        + "; "
        + "tail -n 200 -F "
        + shlex.quote(str(manager_log))
    )
    return shell_join(["bash", "--noprofile", "--norc", "-lc", script])


def tmux_worker_command(
    worker_args: list[str],
    paths: ReviewPaths,
    key: str,
    *,
    keep_window: bool,
    manager_log: Path | None = None,
    round_index: int | None = None,
    window_name: str | None = None,
) -> str:
    banner = (
        f"Claude review key={safe_key(key)}\n"
        f"stdout log: {paths.stdout_log}\n"
        f"stderr log: {paths.stderr_log}\n"
    )
    script = (
        "printf '%s' "
        + shlex.quote(banner)
        + "; "
        + shell_join(worker_args)
        + " 2> >(tee -a "
        + shlex.quote(str(paths.stderr_log))
        + " >&2) | tee -a "
        + shlex.quote(str(paths.stdout_log))
        + "; status=${PIPESTATUS[0]}; printf '\\nClaude review finished with exit=%s\\n' \"$status\"; "
    )
    if manager_log is not None:
        manager_event_cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "_manager_event",
            "--log-path",
            str(manager_log.expanduser()),
            "--event",
            "closed",
            "--field",
            f"key={safe_key(key)}",
            "--field",
            f"stdout_log={paths.stdout_log}",
            "--field",
            f"stderr_log={paths.stderr_log}",
        ]
        if round_index is not None:
            manager_event_cmd.extend(["--field", f"round_index={round_index}"])
        if window_name:
            manager_event_cmd.extend(["--field", f"window_name={window_name}"])
        script += (
            shell_join(manager_event_cmd)
            + " --exit-status \"$status\""
            + "; "
        )
    if keep_window:
        script += "printf 'Logs remain at the paths above. Close this window when done.\\n'; exec bash --noprofile --norc"
    else:
        script += "exit $status"
    return shell_join(["bash", "--noprofile", "--norc", "-lc", script])


def tmux_window_alive(metadata: dict[str, Any]) -> bool | None:
    window_id = metadata.get("tmux_window_id")
    if not isinstance(window_id, str) or not window_id:
        return None
    socket_name = metadata.get("tmux_socket_name")
    proc = subprocess.run(
        [
            *tmux_base_cmd(str(socket_name) if socket_name else None),
            "list-panes",
            "-t",
            window_id,
            "-F",
            "#{pane_dead}",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return False
    pane_states = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return bool(pane_states) and any(state != "1" for state in pane_states)


def ensure_tmux_session(
    base_cmd: list[str],
    session_name: str,
    cwd: Path,
    manager_log: Path,
) -> subprocess.CompletedProcess[str]:
    existing = subprocess.run(
        [*base_cmd, "has-session", "-t", session_name],
        text=True,
        capture_output=True,
        check=False,
    )
    if existing.returncode == 0:
        shell_option = subprocess.run(
            [*base_cmd, "set-option", "-t", session_name, "default-shell", "/bin/bash"],
            text=True,
            capture_output=True,
            check=False,
        )
        if shell_option.returncode != 0:
            return shell_option

        windows = subprocess.run(
            [*base_cmd, "list-windows", "-t", session_name, "-F", "#{window_name}"],
            text=True,
            capture_output=True,
            check=False,
        )
        if windows.returncode != 0:
            return windows
        if "manager" in windows.stdout.splitlines():
            manager = subprocess.run(
                [
                    *base_cmd,
                    "respawn-pane",
                    "-k",
                    "-t",
                    f"{session_name}:manager",
                    tmux_manager_command(manager_log),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
        else:
            manager = subprocess.run(
                [
                    *base_cmd,
                    "new-window",
                    "-d",
                    "-t",
                    f"{session_name}:",
                    "-n",
                    "manager",
                    "-c",
                    str(cwd),
                    tmux_manager_command(manager_log),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
        return manager if manager.returncode != 0 else existing

    created = subprocess.run(
        [
            *base_cmd,
            "new-session",
            "-d",
            "-s",
            session_name,
            "-n",
            "bootstrap",
            "-c",
            str(cwd),
            "sleep 1000000000",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if created.returncode != 0:
        # Another review may have created the manager session between
        # has-session and new-session. Treat that race as success if the
        # session now exists.
        raced = subprocess.run(
            [*base_cmd, "has-session", "-t", session_name],
            text=True,
            capture_output=True,
            check=False,
        )
        if raced.returncode == 0:
            subprocess.run(
                [*base_cmd, "set-option", "-t", session_name, "default-shell", "/bin/bash"],
                text=True,
                capture_output=True,
                check=False,
            )
            return raced
        return created

    shell_option = subprocess.run(
        [*base_cmd, "set-option", "-t", session_name, "default-shell", "/bin/bash"],
        text=True,
        capture_output=True,
        check=False,
    )
    if shell_option.returncode != 0:
        return shell_option

    manager = subprocess.run(
        [
            *base_cmd,
            "new-window",
            "-d",
            "-t",
            f"{session_name}:",
            "-n",
            "manager",
            "-c",
            str(cwd),
            tmux_manager_command(manager_log),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if manager.returncode != 0:
        return manager

    subprocess.run(
        [*base_cmd, "kill-window", "-t", f"{session_name}:bootstrap"],
        text=True,
        capture_output=True,
        check=False,
    )
    return manager


def read_store(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    session_id = data.get("session_id")
    return session_id if isinstance(session_id, str) and session_id else None


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def update_metadata(path: Path, **fields: Any) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        payload = read_json(path)
        payload.update(fields)
        payload["updated_at"] = iso_now()
        atomic_write_json(path, payload)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    return payload


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def read_text_from_offset(path: Path, offset: int) -> str:
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8") as handle:
        handle.seek(offset)
        return handle.read()


def write_store(
    path: Path,
    *,
    key: str,
    session_id: str,
    cwd: Path,
    session_name: str,
    model: str,
    mode: str,
    requirements_present: bool,
) -> None:
    update_metadata(
        path,
        cwd=str(cwd),
        key=key,
        mode=mode,
        model=model,
        requirements_present=requirements_present,
        session_id=session_id,
        session_name=session_name,
    )


def status_payload(metadata: dict[str, Any]) -> dict[str, Any]:
    payload = dict(metadata)
    status = str(payload.get("status") or "missing")
    heartbeat_interval = int(payload.get("heartbeat_interval_seconds") or 30)
    stale_after = max(heartbeat_interval * 2, heartbeat_interval + 5)
    now = epoch_seconds()
    last_heartbeat = epoch_from_iso(payload.get("last_heartbeat_at"))
    last_claude_event = epoch_from_iso(payload.get("last_claude_event_at"))
    last_partial_text = epoch_from_iso(payload.get("last_partial_text_at"))
    started_at = epoch_from_iso(payload.get("started_at"))
    age = None if last_heartbeat is None else max(0, int(now - last_heartbeat))
    claude_event_age = None if last_claude_event is None else max(0, int(now - last_claude_event))
    partial_text_age = None if last_partial_text is None else max(0, int(now - last_partial_text))
    started_age = None if started_at is None else max(0, int(now - started_at))
    tmux_alive = tmux_window_alive(payload)
    alive = tmux_alive if tmux_alive is not None else pid_alive(payload.get("pid"))
    streaming_activity_stale = bool(
        payload.get("streaming")
        and alive
        and (
            (claude_event_age is not None and claude_event_age > stale_after)
            or (claude_event_age is None and started_age is not None and started_age > stale_after)
        )
    )

    if status == "stalled" and age is not None and age <= heartbeat_interval and alive and not streaming_activity_stale:
        status = "running"
    elif status == "stalled" and not alive and age is not None and age > heartbeat_interval:
        status = "crashed"
    elif status == "running" and age is not None and age > stale_after:
        status = "stalled" if alive else "crashed"
    elif status == "running" and not alive and age is not None and age > heartbeat_interval:
        status = "crashed"
    elif status == "running" and streaming_activity_stale:
        status = "stalled"

    payload["status"] = status
    payload["pid_alive"] = alive
    payload["heartbeat_age_seconds"] = age
    payload["stale_after_seconds"] = stale_after
    payload["claude_event_age_seconds"] = claude_event_age
    payload["partial_text_age_seconds"] = partial_text_age
    if payload.get("streaming"):
        if claude_event_age is None:
            payload["claude_activity"] = "streaming-no-events"
        elif claude_event_age <= stale_after:
            payload["claude_activity"] = "streaming-active"
        else:
            payload["claude_activity"] = "streaming-quiet"
    else:
        payload["claude_activity"] = "not-streaming"
    return payload


def cleanup_request_file(payload: dict[str, Any]) -> None:
    request_path = payload.get("request_path")
    if not request_path:
        return
    try:
        Path(str(request_path)).expanduser().unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def reconcile_status(paths: ReviewPaths, metadata: dict[str, Any]) -> dict[str, Any]:
    payload = status_payload(metadata)
    status = payload.get("status")
    stored_status = metadata.get("status")
    if status == "crashed" and stored_status not in TERMINAL_STATUSES:
        cleanup_request_file(payload)
        update_metadata(
            paths.metadata,
            status="crashed",
            completed_at=iso_now(),
            exit_code=None,
        )
        return status_payload(read_json(paths.metadata))
    if status == "stalled" and stored_status == "running":
        update_metadata(paths.metadata, status="stalled")
        return status_payload(read_json(paths.metadata))
    if status == "running" and stored_status == "stalled":
        update_metadata(paths.metadata, status="running")
        return status_payload(read_json(paths.metadata))
    return payload


def truncate_text(label: str, text: str, max_bytes: int) -> str:
    raw = text.encode("utf-8")
    if max_bytes <= 0 or len(raw) <= max_bytes:
        return text
    clipped = raw[:max_bytes].decode("utf-8", errors="ignore")
    return (
        f"{clipped}\n\n[{label} truncated at {max_bytes} bytes; "
        "rerun with --max-diff-bytes 0 for full context.]"
    )


def git_context(cwd: Path, base: str, max_bytes: int, pathspecs: list[str], git_timeout_seconds: int) -> str:
    if not git_output(cwd, ["rev-parse", "--show-toplevel"], timeout=git_timeout_seconds):
        return "[No git repository detected; no diff was captured.]"

    status = git_output(cwd, ["status", "--short"], timeout=git_timeout_seconds)
    diff_args = ["diff", "--find-renames", base, "--"]
    diff_args.extend(pathspecs)
    diff = git_output(cwd, diff_args, timeout=git_timeout_seconds)
    diff = truncate_text("diff", diff, max_bytes)

    if not status and not diff:
        return f"[No tracked changes detected against {base}.]"

    return "\n".join(
        [
            f"Git status:\n{status or '[clean]'}",
            f"Diff against {base}:",
            "```diff",
            diff,
            "```",
        ]
    )


def parse_claude_json(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def extract_stream_text(event: dict[str, Any]) -> str:
    if event.get("type") == "stream_event" and isinstance(event.get("event"), dict):
        return extract_stream_text(event["event"])

    event_type = str(event.get("type") or "")
    if event_type == "result":
        return ""

    pieces: list[str] = []
    if event_type == "content_block_delta":
        delta = event.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("text"), str):
            pieces.append(delta["text"])

    content = event.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                pieces.append(item["text"])
    elif isinstance(content, str) and "partial" in event_type:
        pieces.append(content)

    message = event.get("message")
    if isinstance(message, dict):
        message_content = message.get("content")
        if isinstance(message_content, list):
            for item in message_content:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    pieces.append(item["text"])

    if isinstance(event.get("text"), str) and "partial" in event_type:
        pieces.append(str(event["text"]))

    return "".join(pieces)


def handle_stream_line(
    line: str,
    *,
    paths: ReviewPaths,
    state: StreamMetadataState,
    stream_log: TextIO | None = None,
    metadata_interval_seconds: float = STREAM_METADATA_INTERVAL_SECONDS,
) -> dict[str, Any] | None:
    paths.stream_log.parent.mkdir(parents=True, exist_ok=True)
    if stream_log is None:
        with paths.stream_log.open("a", encoding="utf-8") as owned_stream_log:
            owned_stream_log.write(line)
            owned_stream_log.flush()
    else:
        stream_log.write(line)
        stream_log.flush()

    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(event, dict):
        return None

    state.event_count += 1
    text = extract_stream_text(event)
    now_epoch = epoch_seconds()
    now = iso_from_epoch(now_epoch)
    if text:
        print(text, end="", flush=True)
        state.last_partial_text_at = now

    fields: dict[str, Any] = {
        "status": "running",
        "last_heartbeat_at": now,
        "last_claude_event_at": now,
        "last_claude_event_type": event.get("type"),
        "claude_event_count": state.event_count,
    }
    if state.last_partial_text_at:
        fields["last_partial_text_at"] = state.last_partial_text_at
    try:
        fields["stream_log_bytes"] = paths.stream_log.stat().st_size
    except OSError:
        pass
    should_write = (
        state.last_metadata_update_at <= 0
        or now_epoch - state.last_metadata_update_at >= metadata_interval_seconds
        or event.get("type") == "result"
    )
    if should_write:
        update_metadata(paths.metadata, **fields)
        state.last_metadata_update_at = now_epoch
    return event


def requirements_context(args: argparse.Namespace) -> str:
    parts: list[str] = []

    for index, text in enumerate(args.requirements, start=1):
        stripped = text.strip()
        if stripped:
            parts.append(f"inline requirement {index}:\n{stripped}")

    for file_name in args.requirements_file:
        path = Path(file_name).expanduser()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"Could not read requirements file {path}: {exc}") from exc
        stripped = text.strip()
        if stripped:
            parts.append(f"{path}:\n{stripped}")

    return "\n\n".join(parts)


def has_requirements(args: argparse.Namespace) -> bool:
    return bool(args.requirements or args.requirements_file)


def review_system_prompt(args: argparse.Namespace, has_requirements: bool) -> str:
    parts = [CHILD_SYSTEM_PROMPT, MODE_SYSTEM_PROMPTS[args.mode]]
    if has_requirements:
        parts.append(REQUIREMENTS_SYSTEM_PROMPT)
    if args.system_extra:
        parts.append(args.system_extra.strip())
    return "\n\n".join(part for part in parts if part)


def build_prompt(args: argparse.Namespace, stdin_text: str, include_diff: bool, cwd: Path) -> str:
    user_prompt = " ".join(args.prompt).strip() if args.prompt else ""
    parts = [user_prompt or DEFAULT_PROMPT]

    if stdin_text.strip():
        parts.extend(["Additional input from stdin:", stdin_text.strip()])

    if args.review_path:
        parts.extend(["Files to inspect by path:", "\n".join(args.review_path)])

    reqs = requirements_context(args)
    if reqs:
        parts.extend(["Requirements to check against:", reqs])

    if include_diff:
        parts.extend(
            [
                "Repository changes:",
                git_context(cwd, args.base, args.max_diff_bytes, args.path, args.git_timeout_seconds),
            ]
        )

    return "\n\n".join(parts)


def claude_command(args: argparse.Namespace, session_id: str | None, key: str, requirements_present: bool) -> list[str]:
    tools = "" if args.tools == "none" else READ_ONLY_TOOLS
    output_format = "stream-json" if args.stream else "json"
    cmd = [
        args.claude_bin,
        "-p",
        "--output-format",
        output_format,
        "--model",
        args.model,
        "--tools",
        tools,
        "--disable-slash-commands",
        "--permission-mode",
        "dontAsk",
        "--system-prompt",
        review_system_prompt(args, requirements_present),
        "--name",
        review_session_name(args, key),
    ]
    if tools:
        cmd.extend(["--allowedTools", tools])
    if args.stream:
        cmd.extend(["--include-partial-messages", "--verbose"])
    if args.budget:
        cmd.extend(["--max-budget-usd", args.budget])
    if session_id:
        cmd.extend(["--resume", session_id])
    return cmd


def run_claude(
    args: argparse.Namespace,
    cwd: Path,
    key: str,
    session_id: str | None,
    prompt: str,
    requirements_present: bool,
    paths: ReviewPaths,
) -> ReviewRunResult:
    if args.stream:
        return run_claude_streaming(args, cwd, key, session_id, prompt, requirements_present, paths)

    cmd = claude_command(args, session_id, key, requirements_present)
    paths.metadata.parent.mkdir(parents=True, exist_ok=True)
    prompt_path = paths.metadata.parent / f"{safe_key(key)}.prompt.tmp"
    prompt_path.write_text(prompt, encoding="utf-8")

    timed_out = False
    start_time = epoch_seconds()
    update_metadata(
        paths.metadata,
        status="running",
        pid=os.getpid(),
        started_at=read_json(paths.metadata).get("started_at") or iso_from_epoch(start_time),
        last_heartbeat_at=iso_from_epoch(start_time),
        heartbeat_interval_seconds=args.heartbeat_seconds,
        timeout_seconds=args.timeout_seconds,
        stdout_log_path=str(paths.stdout_log),
        stderr_log_path=str(paths.stderr_log),
        stream_log_path=str(paths.stream_log),
        streaming=False,
    )

    with (
        prompt_path.open("r", encoding="utf-8") as stdin_file,
        paths.stdout_log.open("a+", encoding="utf-8") as stdout_file,
        paths.stderr_log.open("a+", encoding="utf-8") as stderr_file,
    ):
        stdout_file.seek(0, os.SEEK_END)
        stderr_file.seek(0, os.SEEK_END)
        stdout_offset = stdout_file.tell()
        stderr_offset = stderr_file.tell()
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdin=stdin_file,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
        )
        update_metadata(paths.metadata, claude_pid=proc.pid)

        while proc.poll() is None:
            elapsed = epoch_seconds() - start_time
            if args.timeout_seconds and elapsed >= args.timeout_seconds:
                timed_out = True
                proc.kill()
                break
            update_metadata(paths.metadata, status="running", last_heartbeat_at=iso_now())
            sleep_for = max(1, min(args.heartbeat_seconds, 5))
            if args.timeout_seconds:
                sleep_for = max(1, min(sleep_for, int(args.timeout_seconds - elapsed) or 1))
            try:
                proc.wait(timeout=sleep_for)
                break
            except subprocess.TimeoutExpired:
                pass

        returncode = proc.wait()

    try:
        prompt_path.unlink()
    except OSError:
        pass

    stdout = read_text_from_offset(paths.stdout_log, stdout_offset)
    stderr = read_text_from_offset(paths.stderr_log, stderr_offset)
    if timed_out:
        update_metadata(
            paths.metadata,
            status="timeout",
            completed_at=iso_now(),
            duration_s=round(epoch_seconds() - start_time, 3),
            exit_code=returncode,
        )
    return ReviewRunResult(cmd, returncode, stdout, stderr, timed_out)


def run_claude_streaming(
    args: argparse.Namespace,
    cwd: Path,
    key: str,
    session_id: str | None,
    prompt: str,
    requirements_present: bool,
    paths: ReviewPaths,
) -> ReviewRunResult:
    cmd = claude_command(args, session_id, key, requirements_present)
    paths.metadata.parent.mkdir(parents=True, exist_ok=True)
    prompt_path = paths.metadata.parent / f"{safe_key(key)}.prompt.tmp"
    prompt_path.write_text(prompt, encoding="utf-8")

    timed_out = False
    start_time = epoch_seconds()
    last_heartbeat_update_at = start_time
    heartbeat_write_interval = max(1, min(args.heartbeat_seconds, 5))
    stream_state = StreamMetadataState()
    final_event: dict[str, Any] | None = None
    update_metadata(
        paths.metadata,
        status="running",
        pid=os.getpid(),
        started_at=read_json(paths.metadata).get("started_at") or iso_from_epoch(start_time),
        last_heartbeat_at=iso_from_epoch(start_time),
        heartbeat_interval_seconds=args.heartbeat_seconds,
        timeout_seconds=args.timeout_seconds,
        stdout_log_path=str(paths.stdout_log),
        stderr_log_path=str(paths.stderr_log),
        stream_log_path=str(paths.stream_log),
        streaming=True,
        claude_event_count=0,
        last_claude_event_at=None,
        last_claude_event_type=None,
        last_partial_text_at=None,
    )

    with (
        prompt_path.open("r", encoding="utf-8") as stdin_file,
        paths.stderr_log.open("a+", encoding="utf-8") as stderr_file,
        paths.stream_log.open("a", encoding="utf-8") as stream_log,
    ):
        stderr_file.seek(0, os.SEEK_END)
        stderr_offset = stderr_file.tell()
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdin=stdin_file,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            text=True,
            bufsize=1,
        )
        update_metadata(paths.metadata, claude_pid=proc.pid)

        while True:
            now = epoch_seconds()
            elapsed = now - start_time
            if args.timeout_seconds and elapsed >= args.timeout_seconds:
                timed_out = True
                proc.kill()
                break

            if now - last_heartbeat_update_at >= heartbeat_write_interval:
                update_metadata(paths.metadata, status="running", last_heartbeat_at=iso_from_epoch(now))
                last_heartbeat_update_at = now
            sleep_for = heartbeat_write_interval
            if args.timeout_seconds:
                sleep_for = max(1, min(sleep_for, int(args.timeout_seconds - elapsed) or 1))

            if proc.stdout is None:
                break

            ready, _, _ = select.select([proc.stdout], [], [], sleep_for)
            if ready:
                line = proc.stdout.readline()
                if line:
                    event = handle_stream_line(
                        line,
                        paths=paths,
                        state=stream_state,
                        stream_log=stream_log,
                    )
                    if isinstance(event, dict) and event.get("type") == "result":
                        final_event = event
                elif proc.poll() is not None:
                    break

            if proc.poll() is not None:
                for line in proc.stdout:
                    event = handle_stream_line(
                        line,
                        paths=paths,
                        state=stream_state,
                        stream_log=stream_log,
                    )
                    if isinstance(event, dict) and event.get("type") == "result":
                        final_event = event
                break

        returncode = proc.wait()
        if proc.stdout is not None:
            proc.stdout.close()

    try:
        prompt_path.unlink()
    except OSError:
        pass

    stderr = read_text_from_offset(paths.stderr_log, stderr_offset)
    stdout = json.dumps(final_event) if final_event is not None else ""
    if timed_out:
        update_metadata(
            paths.metadata,
            status="timeout",
            completed_at=iso_now(),
            duration_s=round(epoch_seconds() - start_time, 3),
            exit_code=returncode,
        )
    return ReviewRunResult(cmd, returncode, stdout, stderr, timed_out)


def should_retry_without_resume(proc: ReviewRunResult, session_id: str | None, explicit_session: bool) -> bool:
    if not session_id or explicit_session or proc.returncode == 0:
        return False
    combined = f"{proc.stdout}\n{proc.stderr}"
    return "No conversation found with session ID" in combined


def build_start_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a persistent Claude Code review session and store the session id by key."
    )
    parser.add_argument("prompt", nargs="*", help="Review prompt or follow-up question.")
    parser.add_argument("--key", help="Stable name for this review thread.")
    parser.add_argument("--new", action="store_true", help="Start a fresh session and overwrite the stored key.")
    parser.add_argument("--background", action="store_true", help="Start the review in the background and return after writing job metadata.")
    parser.add_argument("--session-id", help="Resume this explicit Claude session id.")
    parser.add_argument("--store-dir", default="~/.claude/review-sessions", help="Directory for key -> session id files.")
    parser.add_argument("--claude-bin", default=os.environ.get("CLAUDE_BIN", "claude"), help="Claude Code executable.")
    parser.add_argument("--model", default=os.environ.get("CLAUDE_REVIEW_MODEL", "sonnet"), help="Claude model alias/name.")
    parser.add_argument("--mode", choices=sorted(MODE_SYSTEM_PROMPTS), default=os.environ.get("CLAUDE_REVIEW_MODE", "implementation"), help="Reviewer stance.")
    parser.add_argument("--requirements", action="append", default=[], help="Requirement/spec text to check against; repeatable.")
    parser.add_argument("--requirements-file", action="append", default=[], help="File containing requirements/spec text; repeatable.")
    parser.add_argument("--review-path", action="append", default=[], help="File or directory path the reviewer may inspect with read-only tools; repeatable.")
    parser.add_argument("--tools", choices=("read-only", "none"), default="read-only", help="Tool policy for child Claude. Default allows Read,Grep,Glob,LS only.")
    parser.add_argument("--system-extra", help="Additional system prompt text appended after the selected mode.")
    parser.add_argument("--session-name-prefix", default=os.environ.get("CLAUDE_REVIEW_SESSION_NAME_PREFIX"), help="Prefix for the child Claude session name.")
    parser.add_argument("--no-session-name-prefix", action="store_true", help="Do not infer a child session-name prefix from caller environment.")
    parser.add_argument("--budget", help="Optional value for claude --max-budget-usd.")
    parser.add_argument("--max-rounds", type=int, default=int(os.environ.get("CLAUDE_REVIEW_MAX_ROUNDS", "3")), help="Maximum review rounds for this key; 0 disables the guardrail.")
    parser.add_argument("--timeout-seconds", type=int, default=0, help="Wall-clock timeout for the child Claude process; 0 disables.")
    parser.add_argument("--heartbeat-seconds", type=int, default=30, help="How often the wrapper updates running metadata.")
    parser.add_argument("--stream", action=argparse.BooleanOptionalAction, default=None, help="Use Claude stream-json and record Claude event activity. Defaults on for background runs.")
    parser.add_argument("--background-launcher", choices=("auto", "subprocess", "tmux"), default="auto", help="How to launch background workers.")
    parser.add_argument("--tmux-session", default=os.environ.get("CLAUDE_REVIEW_TMUX_SESSION", "claude-review"), help="Normal tmux session used for review windows.")
    parser.add_argument("--tmux-socket-name", default=os.environ.get("CLAUDE_REVIEW_TMUX_SOCKET"), help="Optional dedicated tmux socket name. Omit to use the normal tmux server.")
    parser.add_argument("--tmux-keep-window", action=argparse.BooleanOptionalAction, default=False, help="Keep tmux review windows open after completion so final output remains visible.")
    parser.add_argument("--base", default="HEAD", help="Git ref used when capturing a diff.")
    parser.add_argument("--diff", action="store_true", help="Force including git status and diff.")
    parser.add_argument("--no-diff", action="store_true", help="Do not include git status or diff.")
    parser.add_argument("--path", action="append", default=[], help="Git pathspec to include in diff; repeatable.")
    parser.add_argument("--max-diff-bytes", type=int, default=180_000, help="Truncate captured diff at N bytes; 0 disables truncation.")
    parser.add_argument("--git-timeout-seconds", type=int, default=30, help="Timeout for each git command used to capture review context.")
    parser.add_argument("--json", action="store_true", help="Print raw Claude JSON instead of only the result text.")
    parser.add_argument("--dry-run", action="store_true", help="Print resolved settings without calling Claude.")
    return parser


def parse_start_args(argv: list[str]) -> argparse.Namespace:
    return build_start_parser().parse_args(argv)


def next_round_index(args: argparse.Namespace, paths: ReviewPaths, key: str) -> int:
    prepared_round_index = getattr(args, "_prepared_round_index", None)
    if prepared_round_index is not None:
        return int(prepared_round_index)

    previous = 0
    if not args.new:
        metadata = read_json(paths.metadata)
        try:
            previous = int(metadata.get("round_index") or 0)
        except (TypeError, ValueError):
            previous = 0
    round_index = previous + 1
    if args.max_rounds and round_index > args.max_rounds:
        raise SystemExit(
            f"max review rounds exceeded for key={key}: "
            f"round {round_index} > {args.max_rounds}; pass --max-rounds 0 to continue explicitly"
        )
    return round_index


def prepare_start(args: argparse.Namespace, cwd: Path, stdin_text: str) -> tuple[str, ReviewPaths, str | None, bool, bool, str, str, int]:
    key = safe_key(args.key) if args.key else default_key(cwd)
    paths = review_paths(Path(args.store_dir), key)
    if args.review_path and args.tools == "none":
        raise SystemExit("--review-path requires read-only tools; omit --tools none or pipe complete file contents on stdin")
    stored_session_id = None if args.new else read_store(paths.metadata)
    session_id = args.session_id or stored_session_id
    requirements_present = has_requirements(args)
    session_name = review_session_name(args, key)
    include_diff = args.diff or (not args.no_diff and not session_id)
    round_index = next_round_index(args, paths, key)
    prompt = build_prompt(args, stdin_text, include_diff, cwd)
    return key, paths, session_id, requirements_present, include_diff, prompt, session_name, round_index


def start_background(args: argparse.Namespace, cwd: Path, stdin_text: str, start_argv: list[str]) -> int:
    if args.stream is None:
        args.stream = True
    key, paths, session_id, requirements_present, include_diff, prompt, session_name, round_index = prepare_start(args, cwd, stdin_text)
    paths.metadata.parent.mkdir(parents=True, exist_ok=True)
    child_argv = [item for item in start_argv if item != "--background"]
    if args.stream and "--stream" not in child_argv and "--no-stream" not in child_argv:
        child_argv.append("--stream")
    request = {
        "argv": child_argv,
        "cwd": str(cwd),
        "round_index": round_index,
        "stdin_text": stdin_text,
    }
    atomic_write_json(paths.request, request)
    now = iso_now()
    update_metadata(
        paths.metadata,
        key=key,
        cwd=str(cwd),
        status="running",
        completed_at=None,
        duration_s=None,
        exit_code=None,
        error=None,
        errors=None,
        started_at=now,
        last_heartbeat_at=now,
        heartbeat_interval_seconds=args.heartbeat_seconds,
        timeout_seconds=args.timeout_seconds,
        session_id=session_id,
        session_name=session_name,
        mode=args.mode,
        model=args.model,
        round_index=round_index,
        max_rounds=args.max_rounds,
        tmux_keep_window=args.tmux_keep_window,
        requirements_present=requirements_present,
        findings_path=str(paths.findings),
        stdout_log_path=str(paths.stdout_log),
        stderr_log_path=str(paths.stderr_log),
        stream_log_path=str(paths.stream_log),
        request_path=str(paths.request),
        include_diff=include_diff,
        streaming=args.stream,
        claude_event_count=0,
        last_claude_event_at=None,
        last_claude_event_type=None,
        last_partial_text_at=None,
    )
    launcher = resolve_background_launcher(args.background_launcher)
    worker_args = [sys.executable, str(Path(__file__).resolve()), "_worker", "--request-file", str(paths.request)]
    if launcher == "tmux":
        tmux_session_name = args.tmux_session
        manager_log = tmux_manager_log_path(paths.metadata.parent, tmux_session_name)
        append_manager_log(
            manager_log,
            "triggered",
            key=key,
            cwd=cwd,
            round_index=round_index,
            stream=args.stream,
            keep_window=args.tmux_keep_window,
        )
        if not shutil.which("tmux"):
            update_metadata(paths.metadata, status="failed", completed_at=iso_now(), error="tmux not found")
            append_manager_log(manager_log, "failed", key=key, reason="tmux-not-found")
            print("tmux not found for --background-launcher tmux", file=sys.stderr)
            return 1
        base_cmd = tmux_base_cmd(args.tmux_socket_name)
        manager = ensure_tmux_session(base_cmd, tmux_session_name, cwd, manager_log)
        if manager.returncode != 0:
            update_metadata(
                paths.metadata,
                status="failed",
                completed_at=iso_now(),
                exit_code=manager.returncode,
                error=manager.stderr.strip(),
            )
            append_manager_log(manager_log, "failed", key=key, reason="ensure-tmux-session", exit_code=manager.returncode)
            sys.stderr.write(manager.stderr)
            return manager.returncode or 1

        window_name = tmux_window_name(key, round_index)
        shell_cmd = tmux_worker_command(
            worker_args,
            paths,
            key,
            keep_window=args.tmux_keep_window,
            manager_log=manager_log,
            round_index=round_index,
            window_name=window_name,
        )
        launch = subprocess.run(
            [
                *base_cmd,
                "new-window",
                "-d",
                "-P",
                "-F",
                "#{window_id}\t#{pane_id}\t#{pane_pid}",
                "-t",
                f"{tmux_session_name}:",
                "-n",
                window_name,
                "-c",
                str(cwd),
                shell_cmd,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if launch.returncode != 0:
            update_metadata(
                paths.metadata,
                status="failed",
                completed_at=iso_now(),
                exit_code=launch.returncode,
                error=launch.stderr.strip(),
            )
            append_manager_log(manager_log, "failed", key=key, reason="new-window", exit_code=launch.returncode)
            sys.stderr.write(launch.stderr)
            return launch.returncode or 1
        window_id, pane_id, pane_pid = (launch.stdout.strip().split("\t") + ["", "", ""])[:3]
        pid = int(pane_pid) if pane_pid.isdigit() else None
        append_manager_log(
            manager_log,
            "opened",
            key=key,
            window_id=window_id or None,
            window_name=window_name,
            pane_id=pane_id or None,
            pid=pid,
            keep_window=args.tmux_keep_window,
        )
        tmux_fields: dict[str, Any] = {
            "pid": pid,
            "launcher": launcher,
            "tmux_session": tmux_session_name,
            "tmux_window_id": window_id or None,
            "tmux_window_name": window_name,
            "tmux_pane_id": pane_id or None,
            "manager_log_path": str(manager_log),
        }
        if args.tmux_socket_name:
            tmux_fields["tmux_socket_name"] = args.tmux_socket_name
        update_metadata(paths.metadata, **tmux_fields)
    else:
        stdout_file = paths.stdout_log.open("a", encoding="utf-8")
        stderr_file = paths.stderr_log.open("a", encoding="utf-8")
        proc = subprocess.Popen(
            worker_args,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            start_new_session=True,
        )
        stdout_file.close()
        stderr_file.close()
        update_metadata(paths.metadata, pid=proc.pid, launcher=launcher)
    payload = status_payload(read_json(paths.metadata))
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"claude_review_session key={key} status=running pid={payload.get('pid')} stored={paths.metadata}")
    return 0


def execute_start(args: argparse.Namespace, cwd: Path, stdin_text: str) -> int:
    if args.stream is None:
        args.stream = False
    key, paths, session_id, requirements_present, include_diff, prompt, session_name, round_index = prepare_start(args, cwd, stdin_text)
    explicit_session = bool(args.session_id)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "key": key,
                    "store_path": str(paths.metadata),
                    "resume_session_id": session_id,
                    "include_diff": include_diff,
                    "mode": args.mode,
                    "round_index": round_index,
                    "max_rounds": args.max_rounds,
                    "streaming": args.stream,
                    "prompt_bytes": len(prompt.encode("utf-8")),
                    "requirements_present": requirements_present,
                    "session_name": session_name,
                    "command": claude_command(args, session_id, key, requirements_present),
                },
                indent=2,
            )
        )
        return 0

    start_time = epoch_seconds()
    update_metadata(
        paths.metadata,
        key=key,
        cwd=str(cwd),
        status="running",
        completed_at=None,
        duration_s=None,
        exit_code=None,
        error=None,
        errors=None,
        started_at=iso_from_epoch(start_time),
        session_id=session_id,
        session_name=session_name,
        mode=args.mode,
        model=args.model,
        round_index=round_index,
        max_rounds=args.max_rounds,
        requirements_present=requirements_present,
        findings_path=str(paths.findings),
        include_diff=include_diff,
        streaming=args.stream,
    )

    proc = run_claude(args, cwd, key, session_id, prompt, requirements_present, paths)
    if should_retry_without_resume(proc, session_id, explicit_session):
        print(f"Stored Claude session was not found; starting a fresh session for key={key}.", file=sys.stderr)
        session_id = None
        prompt = build_prompt(args, stdin_text, True, cwd)
        proc = run_claude(args, cwd, key, None, prompt, requirements_present, paths)

    data = parse_claude_json(proc.stdout)
    if data is None:
        sys.stderr.write(proc.stderr)
        sys.stdout.write(proc.stdout)
        update_metadata(
            paths.metadata,
            status="timeout" if proc.timed_out else "failed",
            completed_at=iso_now(),
            duration_s=round(epoch_seconds() - start_time, 3),
            exit_code=proc.returncode,
        )
        return proc.returncode or 1

    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        result = data.get("result")
        if isinstance(result, str):
            print(result)
        else:
            print(json.dumps(data, indent=2, sort_keys=True))

    child_session_id = data.get("session_id")
    if proc.returncode == 0 and not data.get("is_error") and isinstance(child_session_id, str):
        result = data.get("result") if isinstance(data.get("result"), str) else proc.stdout
        write_text_atomic(paths.findings, result)
        update_metadata(
            paths.metadata,
            status="done",
            completed_at=iso_now(),
            duration_s=round(epoch_seconds() - start_time, 3),
            exit_code=proc.returncode,
            session_id=child_session_id,
            findings_path=str(paths.findings),
            key=key,
            cwd=str(cwd),
            session_name=session_name,
            model=args.model,
            mode=args.mode,
            round_index=round_index,
            max_rounds=args.max_rounds,
            requirements_present=requirements_present,
        )
        cost = data.get("total_cost_usd")
        cost_part = f" cost_usd={cost}" if cost is not None else ""
        print(f"claude_review_session key={key} session_id={child_session_id} stored={paths.metadata}{cost_part}", file=sys.stderr)
        return 0

    sys.stderr.write(proc.stderr)
    errors = data.get("errors")
    if errors:
        print(f"claude_review_session errors={errors}", file=sys.stderr)
    update_metadata(
        paths.metadata,
        status="timeout" if proc.timed_out else "failed",
        completed_at=iso_now(),
        duration_s=round(epoch_seconds() - start_time, 3),
        exit_code=proc.returncode,
        errors=errors,
    )
    return proc.returncode or 1


def load_key_metadata(store_dir: str, key: str) -> tuple[ReviewPaths, dict[str, Any]]:
    paths = review_paths(Path(store_dir), key)
    return paths, read_json(paths.metadata)


def command_status(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Show persistent Claude review status.")
    parser.add_argument("--key", required=True)
    parser.add_argument("--store-dir", default="~/.claude/review-sessions")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    paths, metadata = load_key_metadata(args.store_dir, args.key)
    if not metadata:
        payload = {"key": safe_key(args.key), "status": "missing", "store_path": str(paths.metadata)}
    else:
        payload = reconcile_status(paths, metadata)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(payload.get("status", "missing"))
    return 0 if payload.get("status") not in {"failed", "timeout", "crashed", "missing"} else 1


def command_result(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Print findings for a persistent Claude review.")
    parser.add_argument("--key", required=True)
    parser.add_argument("--store-dir", default="~/.claude/review-sessions")
    args = parser.parse_args(argv)
    paths, metadata = load_key_metadata(args.store_dir, args.key)
    payload = status_payload(metadata) if metadata else {"status": "missing"}
    if payload.get("status") != "done":
        print(f"Review is not done: {payload.get('status')}", file=sys.stderr)
        return 1
    findings_path = Path(str(payload.get("findings_path") or paths.findings)).expanduser()
    if not findings_path.exists():
        print(f"Findings file missing: {findings_path}", file=sys.stderr)
        return 1
    print(findings_path.read_text(encoding="utf-8"), end="")
    return 0


def command_check(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Check a persistent Claude review once without waiting.")
    parser.add_argument("--key", required=True)
    parser.add_argument("--store-dir", default="~/.claude/review-sessions")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--result", action="store_true", help="Print findings instead of status when the review is done.")
    args = parser.parse_args(argv)

    paths, metadata = load_key_metadata(args.store_dir, args.key)
    payload = reconcile_status(paths, metadata) if metadata else {"key": safe_key(args.key), "status": "missing", "store_path": str(paths.metadata)}
    status = str(payload.get("status") or "missing")

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.result and status == "done":
        findings_path = Path(str(payload.get("findings_path") or paths.findings)).expanduser()
        if not findings_path.exists():
            print(f"Findings file missing: {findings_path}", file=sys.stderr)
            return 1
        print(findings_path.read_text(encoding="utf-8"), end="")
    else:
        print(status)

    if status == "done":
        return 0
    if status in TERMINAL_STATUSES or status == "missing":
        return 1
    return 2


def command_manager_event(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=argparse.SUPPRESS)
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--field", action="append", default=[])
    parser.add_argument("--exit-status")
    args = parser.parse_args(argv)

    fields: dict[str, Any] = {}
    for field in args.field:
        if "=" not in field:
            continue
        name, value = field.split("=", 1)
        if name:
            fields[name] = value
    if args.exit_status is not None:
        fields["exit"] = args.exit_status
    append_manager_log(Path(args.log_path), args.event, **fields)
    return 0


def terminate_pid(pid: Any) -> None:
    if not isinstance(pid, int) or pid <= 0:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        return
    except OSError:
        return


def command_cancel(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Cancel a persistent Claude review.")
    parser.add_argument("--key", required=True)
    parser.add_argument("--store-dir", default="~/.claude/review-sessions")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    paths, metadata = load_key_metadata(args.store_dir, args.key)
    if not metadata:
        payload = {"key": safe_key(args.key), "status": "missing", "store_path": str(paths.metadata)}
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print("missing")
        return 1

    if metadata.get("status") in TERMINAL_STATUSES:
        payload = status_payload(metadata)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(payload.get("status", "missing"))
        return 0

    tmux_window_id = metadata.get("tmux_window_id")
    tmux_socket_name = metadata.get("tmux_socket_name")
    manager_log_path = metadata.get("manager_log_path")
    if isinstance(tmux_window_id, str) and tmux_window_id:
        subprocess.run(
            [*tmux_base_cmd(str(tmux_socket_name) if tmux_socket_name else None), "kill-window", "-t", tmux_window_id],
            text=True,
            capture_output=True,
            check=False,
        )
        if isinstance(manager_log_path, str) and manager_log_path:
            append_manager_log(
                Path(manager_log_path),
                "cancelled",
                key=metadata.get("key") or safe_key(args.key),
                window_id=tmux_window_id,
                window_name=metadata.get("tmux_window_name"),
            )
    else:
        terminate_pid(metadata.get("claude_pid"))
        terminate_pid(metadata.get("pid"))

    cleanup_request_file(metadata)
    update_metadata(
        paths.metadata,
        status="cancelled",
        completed_at=iso_now(),
        exit_code=None,
    )
    payload = status_payload(read_json(paths.metadata))
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("cancelled")
    return 0


def command_wait(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Wait for a persistent Claude review to finish.")
    parser.add_argument("--key", required=True)
    parser.add_argument("--store-dir", default="~/.claude/review-sessions")
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    deadline = epoch_seconds() + args.timeout_seconds if args.timeout_seconds else None
    last_status = None
    while True:
        paths, metadata = load_key_metadata(args.store_dir, args.key)
        payload = reconcile_status(paths, metadata) if metadata else {"key": safe_key(args.key), "status": "missing", "store_path": str(paths.metadata)}
        status = payload.get("status")
        if status != last_status and not args.json:
            print(status)
            last_status = status
        if status in TERMINAL_STATUSES or status == "missing":
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            return 0 if status == "done" else 1
        if status == "stalled":
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            return 2
        if deadline and epoch_seconds() >= deadline:
            print("wait-timeout", file=sys.stderr)
            return 2
        time.sleep(max(1, args.poll_seconds))


def command_worker(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=argparse.SUPPRESS)
    parser.add_argument("--request-file", required=True)
    args = parser.parse_args(argv)
    request_path = Path(args.request_file)
    request = read_json(request_path)
    start_args = parse_start_args(list(request.get("argv") or []))
    start_args.background = False
    if "round_index" in request:
        start_args._prepared_round_index = int(request["round_index"])
    cwd = Path(str(request.get("cwd") or Path.cwd()))
    stdin_text = str(request.get("stdin_text") or "")
    try:
        return execute_start(start_args, cwd, stdin_text)
    finally:
        try:
            request_path.unlink()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "start":
        start_argv = argv[1:]
    elif argv and argv[0] == "status":
        return command_status(argv[1:])
    elif argv and argv[0] == "wait":
        return command_wait(argv[1:])
    elif argv and argv[0] == "result":
        return command_result(argv[1:])
    elif argv and argv[0] == "check":
        return command_check(argv[1:])
    elif argv and argv[0] == "cancel":
        return command_cancel(argv[1:])
    elif argv and argv[0] == "_manager_event":
        return command_manager_event(argv[1:])
    elif argv and argv[0] == "_worker":
        return command_worker(argv[1:])
    else:
        start_argv = argv

    args = parse_start_args(start_argv)
    stdin_text = "" if sys.stdin.isatty() else sys.stdin.read()
    cwd = Path.cwd()
    if args.background and not args.dry_run:
        return start_background(args, cwd, stdin_text, start_argv)
    return execute_start(args, cwd, stdin_text)


if __name__ == "__main__":
    raise SystemExit(main())
