import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import io
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "claude_review_session.py"


def load_module():
    spec = importlib.util.spec_from_file_location("claude_review_session", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = load_module()


def args(**overrides):
    values = {
        "base": "HEAD",
        "budget": None,
        "claude_bin": "claude",
        "git_timeout_seconds": 30,
        "max_diff_bytes": 180_000,
        "mode": "implementation",
        "model": "sonnet",
        "no_session_name_prefix": False,
        "path": [],
        "prompt": ["Review this change."],
        "requirements": [],
        "requirements_file": [],
        "review_path": [],
        "session_name_prefix": None,
        "stream": False,
        "system_extra": None,
        "tmux_keep_window": False,
        "tmux_runner_idle_seconds": None,
        "tools": "read-only",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def cleanup_tmux_session(name):
    subprocess.run(
        ["tmux", "kill-session", "-t", name],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


def tmux_window_exists(window_id):
    proc = subprocess.run(
        ["tmux", "has-session", "-t", window_id],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    return proc.returncode == 0


def wait_for_tmux_window_absent(window_id, timeout_seconds=3):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not tmux_window_exists(window_id):
            return True
        time.sleep(0.1)
    return not tmux_window_exists(window_id)


@contextmanager
def patched_env(**updates):
    original = {name: os.environ.get(name) for name in updates}
    try:
        for name, value in updates.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class ClaudeReviewSessionTests(unittest.TestCase):
    def test_system_prompt_modes_and_requirements(self):
        implementation = mod.review_system_prompt(args(mode="implementation"), has_requirements=False)
        self.assertIn("correctness bugs", implementation)
        self.assertIn("Do not claim spec compliance", implementation)

        adversarial = mod.review_system_prompt(args(mode="adversarial"), has_requirements=False)
        self.assertIn("Challenge design assumptions", adversarial)
        self.assertIn("Only report risks", adversarial)

        with_requirements = mod.review_system_prompt(args(mode="implementation"), has_requirements=True)
        self.assertIn("Compare the implementation against the supplied requirements", with_requirements)

        extra = mod.review_system_prompt(
            args(system_extra="Prefer API compatibility risks."),
            has_requirements=True,
        )
        self.assertIn("Prefer API compatibility risks.", extra)

    def test_prompt_includes_requirements_text_and_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            req_file = Path(tmpdir) / "requirements.md"
            req_file.write_text("Must preserve existing CLI flags.\n", encoding="utf-8")

            prompt = mod.build_prompt(
                args(
                    requirements=["Must not edit files."],
                    requirements_file=[str(req_file)],
                ),
                "",
                False,
                Path.cwd(),
            )

        self.assertIn("Requirements to check against:", prompt)
        self.assertIn("Must not edit files.", prompt)
        self.assertIn("requirements.md:", prompt)
        self.assertIn("Must preserve existing CLI flags.", prompt)
        self.assertNotIn("Repository changes:", prompt)

    def test_prompt_includes_review_paths_for_read_only_reviewer(self):
        prompt = mod.build_prompt(
            args(review_path=["scripts/reviewer.py", "tests/test_reviewer.py"]),
            "",
            False,
            Path.cwd(),
        )

        self.assertIn("Files to inspect by path:", prompt)
        self.assertIn("scripts/reviewer.py", prompt)
        self.assertIn("tests/test_reviewer.py", prompt)

    def test_review_session_name_uses_explicit_or_env_prefix(self):
        self.assertEqual(
            mod.review_session_name(args(session_name_prefix="Parent Session"), "feature/key"),
            "Parent-Session-review-feature-key",
        )

        with patched_env(CODEX_THREAD_ID="019e2767-150a-7433-b388-339d7c9853a4"):
            self.assertEqual(
                mod.review_session_name(args(), "feature/key"),
                "codex-019e2767-review-feature-key",
            )

        self.assertEqual(
            mod.review_session_name(args(no_session_name_prefix=True), "feature/key"),
            "review-feature-key",
        )

    def test_review_session_name_truncation_preserves_key_uniqueness(self):
        prefix = "same-prefix-" * 12
        first = mod.review_session_name(args(session_name_prefix="Parent"), prefix + "alpha")
        second = mod.review_session_name(args(session_name_prefix="Parent"), prefix + "bravo")

        self.assertLessEqual(len(first), 120)
        self.assertLessEqual(len(second), 120)
        self.assertNotEqual(first, second)

    def test_tmux_window_name_includes_round_index_when_available(self):
        self.assertEqual(mod.tmux_window_name("feature/key"), "review-feature-key")
        self.assertEqual(mod.tmux_window_name("feature/key", 0), "review-feature-key-r0")
        self.assertEqual(mod.tmux_window_name("feature/key", 3), "review-feature-key-r3")
        self.assertLessEqual(len(mod.tmux_window_name("long-key-" * 20, 42)), 80)

    def test_claude_command_defaults_to_read_only_tools_and_names_session(self):
        command = mod.claude_command(
            args(session_name_prefix="Parent Session", mode="adversarial"),
            session_id="session-123",
            key="feature/key",
            requirements_present=True,
        )

        self.assertIn("--disable-slash-commands", command)
        self.assertEqual(command[command.index("--tools") + 1], "Read,Grep,Glob,LS")
        self.assertEqual(command[command.index("--allowedTools") + 1], "Read,Grep,Glob,LS")
        self.assertEqual(command[command.index("--name") + 1], "Parent-Session-review-feature-key")
        self.assertIn("--resume", command)
        self.assertEqual(command[command.index("--resume") + 1], "session-123")
        self.assertIn("Challenge design assumptions", command[command.index("--system-prompt") + 1])
        self.assertIn("Compare the implementation against the supplied requirements", command[command.index("--system-prompt") + 1])

        no_tools = mod.claude_command(
            args(tools="none"),
            session_id=None,
            key="feature/key",
            requirements_present=False,
        )
        self.assertEqual(no_tools[no_tools.index("--tools") + 1], "")
        self.assertNotIn("--allowedTools", no_tools)

        stream = mod.claude_command(
            args(stream=True),
            session_id=None,
            key="feature/key",
            requirements_present=False,
        )
        self.assertEqual(stream[stream.index("--output-format") + 1], "stream-json")
        self.assertIn("--include-partial-messages", stream)
        self.assertIn("--verbose", stream)

    def test_store_round_trip_is_json_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "review-key.json"
            mod.write_store(
                store_path,
                key="review-key",
                session_id="session-123",
                cwd=Path(tmpdir),
                session_name="parent-review-key",
                model="sonnet",
                mode="implementation",
                requirements_present=True,
            )

            self.assertEqual(mod.read_store(store_path), "session-123")
            payload = json.loads(store_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["key"], "review-key")
        self.assertEqual(payload["session_name"], "parent-review-key")
        self.assertEqual(payload["model"], "sonnet")
        self.assertTrue(payload["requirements_present"])

    def test_review_paths_are_keyed_and_relative_to_store_dir(self):
        paths = mod.review_paths(Path("/tmp/reviews"), "feature/key")

        self.assertEqual(paths.metadata, Path("/tmp/reviews/feature-key.json"))
        self.assertEqual(paths.findings, Path("/tmp/reviews/feature-key.findings.md"))
        self.assertEqual(paths.stdout_log, Path("/tmp/reviews/feature-key.stdout.log"))
        self.assertEqual(paths.stderr_log, Path("/tmp/reviews/feature-key.stderr.log"))
        self.assertEqual(paths.stream_log, Path("/tmp/reviews/feature-key.stream.jsonl"))
        self.assertEqual(paths.request, Path("/tmp/reviews/feature-key.request.json"))

    def test_queue_claim_renames_request_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_dir = Path(tmpdir) / "review-key.queue"
            queue_dir.mkdir()
            request = queue_dir / "1.json"
            request.write_text('{"prompt":"review"}\n', encoding="utf-8")

            claimed = mod.claim_queued_request(request)
            claimed_again = mod.claim_queued_request(request)

            self.assertIsNotNone(claimed)
            self.assertFalse(request.exists())
            self.assertTrue(claimed.exists())
            self.assertIsNone(claimed_again)
            self.assertEqual(mod.queued_request_files(queue_dir), [])

    def test_run_returns_timeout_completed_process(self):
        proc = mod.run(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            Path.cwd(),
            timeout=0.1,
        )

        self.assertEqual(proc.returncode, 124)
        self.assertIn("timed out", proc.stderr)

    def test_extract_stream_text_handles_verbose_stream_event_wrapper(self):
        text = mod.extract_stream_text(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "wrapped partial"},
                },
            }
        )

        self.assertEqual(text, "wrapped partial")

    def test_status_payload_classifies_running_stalled_and_crashed(self):
        fresh = mod.iso_now()
        stale = mod.iso_from_epoch(mod.epoch_seconds() - 120)

        running = mod.status_payload(
            {
                "status": "running",
                "pid": os.getpid(),
                "last_heartbeat_at": fresh,
                "heartbeat_interval_seconds": 60,
            }
        )
        self.assertEqual(running["status"], "running")
        self.assertTrue(running["pid_alive"])

        stalled = mod.status_payload(
            {
                "status": "running",
                "pid": os.getpid(),
                "last_heartbeat_at": stale,
                "heartbeat_interval_seconds": 30,
            }
        )
        self.assertEqual(stalled["status"], "stalled")
        self.assertTrue(stalled["pid_alive"])

        crashed = mod.status_payload(
            {
                "status": "running",
                "pid": 999999999,
                "last_heartbeat_at": stale,
                "heartbeat_interval_seconds": 30,
            }
        )
        self.assertEqual(crashed["status"], "crashed")
        self.assertFalse(crashed["pid_alive"])

    def test_status_payload_reports_streaming_activity_age(self):
        fresh = mod.iso_now()
        stale = mod.iso_from_epoch(mod.epoch_seconds() - 120)

        active = mod.status_payload(
            {
                "status": "running",
                "pid": os.getpid(),
                "streaming": True,
                "last_heartbeat_at": fresh,
                "last_claude_event_at": fresh,
                "heartbeat_interval_seconds": 30,
            }
        )
        self.assertEqual(active["claude_activity"], "streaming-active")
        self.assertIsNotNone(active["claude_event_age_seconds"])

        quiet = mod.status_payload(
            {
                "status": "running",
                "pid": os.getpid(),
                "streaming": True,
                "last_heartbeat_at": fresh,
                "last_claude_event_at": stale,
                "heartbeat_interval_seconds": 30,
            }
        )
        self.assertEqual(quiet["status"], "stalled")
        self.assertEqual(quiet["claude_activity"], "streaming-quiet")

        no_events = mod.status_payload(
            {
                "status": "running",
                "pid": os.getpid(),
                "streaming": True,
                "last_heartbeat_at": fresh,
                "heartbeat_interval_seconds": 30,
            }
        )
        self.assertEqual(no_events["claude_activity"], "streaming-no-events")

        no_events_too_long = mod.status_payload(
            {
                "status": "running",
                "pid": os.getpid(),
                "streaming": True,
                "started_at": stale,
                "last_heartbeat_at": fresh,
                "heartbeat_interval_seconds": 30,
            }
        )
        self.assertEqual(no_events_too_long["status"], "stalled")
        self.assertEqual(no_events_too_long["claude_activity"], "streaming-no-events")

    def test_reconcile_keeps_streaming_stalled_status_stable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = mod.review_paths(Path(tmpdir), "streaming-stalled")
            fresh = mod.iso_now()
            stale = mod.iso_from_epoch(mod.epoch_seconds() - 120)
            mod.atomic_write_json(
                paths.metadata,
                {
                    "status": "stalled",
                    "pid": os.getpid(),
                    "streaming": True,
                    "started_at": stale,
                    "last_heartbeat_at": fresh,
                    "last_claude_event_at": stale,
                    "heartbeat_interval_seconds": 30,
                },
            )

            first = mod.reconcile_status(paths, mod.read_json(paths.metadata))
            second = mod.reconcile_status(paths, mod.read_json(paths.metadata))

            self.assertEqual(first["status"], "stalled")
            self.assertEqual(second["status"], "stalled")
            self.assertEqual(mod.read_json(paths.metadata)["status"], "stalled")

    def test_status_payload_treats_no_event_missing_started_stale_heartbeat_as_streaming_stale(self):
        stale = mod.iso_from_epoch(mod.epoch_seconds() - 120)

        payload = mod.status_payload(
            {
                "status": "running",
                "pid": os.getpid(),
                "streaming": True,
                "last_heartbeat_at": stale,
                "heartbeat_interval_seconds": 30,
            }
        )

        self.assertEqual(payload["status"], "stalled")
        self.assertEqual(payload["claude_activity"], "streaming-no-events")

    def test_tmux_commands_are_visible_without_login_shell_manager(self):
        manager_log = Path("/tmp/reviews/claude-review.manager.log")
        manager = mod.tmux_manager_command(manager_log)

        self.assertNotIn("sh -l", manager)
        self.assertNotIn("source", manager)
        self.assertIn("Claude review manager", manager)
        self.assertIn("Manager log: /tmp/reviews/claude-review.manager.log", manager)
        self.assertIn("%s\\n", manager)
        self.assertIn("tail -n 200 -F /tmp/reviews/claude-review.manager.log", manager)

        paths = mod.review_paths(Path("/tmp/reviews"), "feature/key")
        worker = mod.tmux_worker_command(
            ["python", "worker.py"],
            paths,
            "feature/key",
            keep_window=True,
            manager_log=Path("/tmp/reviews/manager.log"),
            round_index=2,
            window_name="review-feature-key-r2",
        )

        self.assertIn("Claude review key=feature-key", worker)
        self.assertIn("stdout log: /tmp/reviews/feature-key.stdout.log", worker)
        self.assertIn("stderr log: /tmp/reviews/feature-key.stderr.log", worker)
        self.assertTrue(worker.startswith("bash --noprofile --norc -lc "))
        self.assertIn("python worker.py 2> >(tee -a /tmp/reviews/feature-key.stderr.log >&2)", worker)
        self.assertIn("| tee -a /tmp/reviews/feature-key.stdout.log", worker)
        self.assertIn("Claude review finished with exit=", worker)
        self.assertIn("_manager_event", worker)
        self.assertIn("--event closed", worker)
        self.assertIn("--field round_index=2", worker)
        self.assertIn("--field window_name=review-feature-key-r2", worker)
        self.assertIn("exec bash --noprofile --norc", worker)

        close_worker = mod.tmux_worker_command(["python", "worker.py"], paths, "feature/key", keep_window=False)
        self.assertIn("exit $status", close_worker)
        self.assertNotIn("exec bash --noprofile --norc", close_worker)

    def test_start_parser_supports_background_lifecycle_flags(self):
        parsed = mod.parse_start_args(
            [
                "--key",
                "review-key",
                "--background",
                "--timeout-seconds",
                "900",
                "--heartbeat-seconds",
                "15",
                "--background-launcher",
                "tmux",
                "--tmux-session",
                "claude-review-test",
                "--review-path",
                "scripts/reviewer.py",
                "Review this.",
            ]
        )

        self.assertTrue(parsed.background)
        self.assertEqual(parsed.timeout_seconds, 900)
        self.assertEqual(parsed.heartbeat_seconds, 15)
        self.assertEqual(parsed.background_launcher, "tmux")
        self.assertEqual(parsed.tmux_session, "claude-review-test")
        self.assertIsNone(parsed.tmux_socket_name)
        self.assertEqual(parsed.review_path, ["scripts/reviewer.py"])
        self.assertEqual(parsed.tools, "read-only")
        self.assertIsNone(parsed.stream)
        self.assertFalse(parsed.tmux_keep_window)
        self.assertEqual(parsed.prompt, ["Review this."])

    def test_background_lifecycle_with_fake_claude(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            fake_claude = tmp_path / "fake_claude.py"
            fake_claude.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json, sys, time",
                        "sys.stdin.read()",
                        "time.sleep(0.1)",
                        "print(json.dumps({",
                        "  'type': 'result',",
                        "  'subtype': 'success',",
                        "  'is_error': False,",
                        "  'result': 'fake-review-ok',",
                        "  'session_id': 'fake-session',",
                        "  'total_cost_usd': 0",
                        "}))",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)

            start = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "start",
                    "--background",
                    "--background-launcher",
                    "subprocess",
                    "--key",
                    "bg-test",
                    "--store-dir",
                    tmpdir,
                    "--claude-bin",
                    str(fake_claude),
                    "--no-diff",
                    "--heartbeat-seconds",
                    "1",
                    "Review this.",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(start.returncode, 0, start.stderr)

            wait = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "wait",
                    "--key",
                    "bg-test",
                    "--store-dir",
                    tmpdir,
                    "--poll-seconds",
                    "1",
                    "--timeout-seconds",
                    "5",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(wait.returncode, 0, wait.stderr)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "result",
                    "--key",
                    "bg-test",
                    "--store-dir",
                    tmpdir,
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "fake-review-ok")

            metadata = json.loads((tmp_path / "bg-test.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "done")
            self.assertEqual(metadata["round_index"], 1)
            self.assertEqual(metadata["launcher"], "subprocess")
            self.assertTrue(metadata["streaming"])
            self.assertEqual(metadata["claude_event_count"], 1)
            self.assertEqual(metadata["last_claude_event_type"], "result")
            self.assertIsNotNone(metadata["last_claude_event_at"])
            self.assertEqual(metadata["session_id"], "fake-session")
            self.assertEqual(metadata["findings_path"], str(tmp_path / "bg-test.findings.md"))

    def test_background_no_stream_keeps_legacy_json_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            fake_claude = tmp_path / "fake_json_claude.py"
            fake_claude.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json, sys",
                        "sys.stdin.read()",
                        "print(json.dumps({",
                        "  'type': 'result',",
                        "  'subtype': 'success',",
                        "  'is_error': False,",
                        "  'result': 'fake-json-review-ok',",
                        "  'session_id': 'fake-json-session',",
                        "  'total_cost_usd': 0",
                        "}))",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)

            start = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "start",
                    "--background",
                    "--background-launcher",
                    "subprocess",
                    "--no-stream",
                    "--key",
                    "bg-json-test",
                    "--store-dir",
                    tmpdir,
                    "--claude-bin",
                    str(fake_claude),
                    "--no-diff",
                    "--heartbeat-seconds",
                    "1",
                    "Review this.",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(start.returncode, 0, start.stderr)

            wait = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "wait",
                    "--key",
                    "bg-json-test",
                    "--store-dir",
                    tmpdir,
                    "--poll-seconds",
                    "1",
                    "--timeout-seconds",
                    "5",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(wait.returncode, 0, wait.stderr)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "result",
                    "--key",
                    "bg-json-test",
                    "--store-dir",
                    tmpdir,
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "fake-json-review-ok")

            metadata = json.loads((tmp_path / "bg-json-test.json").read_text(encoding="utf-8"))
            self.assertFalse(metadata["streaming"])
            self.assertEqual(metadata["session_id"], "fake-json-session")
            self.assertFalse((tmp_path / "bg-json-test.stream.jsonl").exists())

    def test_new_background_run_clears_previous_terminal_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            fake_claude = tmp_path / "slow_fake_claude.py"
            fake_claude.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import sys, time",
                        "sys.stdin.read()",
                        "time.sleep(30)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)
            mod.atomic_write_json(
                tmp_path / "clear-terminal.json",
                {
                    "key": "clear-terminal",
                    "status": "done",
                    "completed_at": "2026-05-14T00:00:00+00:00",
                    "duration_s": 12.3,
                    "exit_code": 0,
                    "session_id": "previous-session",
                    "round_index": 1,
                },
            )

            start = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "start",
                    "--background",
                    "--background-launcher",
                    "subprocess",
                    "--key",
                    "clear-terminal",
                    "--store-dir",
                    tmpdir,
                    "--claude-bin",
                    str(fake_claude),
                    "--no-diff",
                    "--heartbeat-seconds",
                    "1",
                    "Review this.",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(start.returncode, 0, start.stderr)

            metadata = json.loads((tmp_path / "clear-terminal.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "running")
            self.assertIsNone(metadata["completed_at"])
            self.assertIsNone(metadata["duration_s"])
            self.assertIsNone(metadata["exit_code"])

            cancel = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "cancel",
                    "--key",
                    "clear-terminal",
                    "--store-dir",
                    tmpdir,
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(cancel.returncode, 0, cancel.stderr)

    def test_foreground_followup_parses_only_current_claude_output_when_logs_append(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            counter = tmp_path / "counter.txt"
            fake_claude = tmp_path / "fake_claude.py"
            fake_claude.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json, pathlib, sys",
                        f"counter = pathlib.Path({str(counter)!r})",
                        "count = int(counter.read_text() or '0') + 1 if counter.exists() else 1",
                        "counter.write_text(str(count))",
                        "sys.stdin.read()",
                        "print(json.dumps({",
                        "  'type': 'result',",
                        "  'subtype': 'success',",
                        "  'is_error': False,",
                        "  'result': f'review-{count}',",
                        "  'session_id': f'fake-session-{count}',",
                        "  'total_cost_usd': 0",
                        "}))",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)

            common = [
                sys.executable,
                str(SCRIPT),
                "start",
                "--key",
                "append-test",
                "--store-dir",
                tmpdir,
                "--claude-bin",
                str(fake_claude),
                "--no-diff",
            ]
            first = subprocess.run(
                [*common, "First review."],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(first.returncode, 0, first.stderr)

            second = subprocess.run(
                [*common, "Follow up review."],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(second.stdout, "review-2\n")

            metadata = json.loads((tmp_path / "append-test.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["session_id"], "fake-session-2")
            self.assertEqual((tmp_path / "append-test.findings.md").read_text(encoding="utf-8"), "review-2")

    def test_streaming_run_records_claude_activity_and_final_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            fake_claude = tmp_path / "fake_stream_claude.py"
            fake_claude.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json, sys, time",
                        "sys.stdin.read()",
                        "print(json.dumps({'type': 'system', 'subtype': 'init'}), flush=True)",
                        "time.sleep(0.05)",
                        "print(json.dumps({'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'partial review'}}), flush=True)",
                        "time.sleep(0.05)",
                        "print(json.dumps({",
                        "  'type': 'result',",
                        "  'subtype': 'success',",
                        "  'is_error': False,",
                        "  'result': 'stream-final-review',",
                        "  'session_id': 'fake-stream-session',",
                        "  'total_cost_usd': 0",
                        "}), flush=True)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)

            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "start",
                    "--stream",
                    "--key",
                    "stream-test",
                    "--store-dir",
                    tmpdir,
                    "--claude-bin",
                    str(fake_claude),
                    "--no-diff",
                    "Review this.",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("partial review", proc.stdout)
            self.assertIn("stream-final-review", proc.stdout)

            metadata = json.loads((tmp_path / "stream-test.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "done")
            self.assertTrue(metadata["streaming"])
            self.assertGreaterEqual(metadata["claude_event_count"], 2)
            self.assertEqual(metadata["last_claude_event_type"], "result")
            self.assertIsNotNone(metadata["last_claude_event_at"])
            self.assertIsNotNone(metadata["last_partial_text_at"])
            self.assertEqual((tmp_path / "stream-test.findings.md").read_text(encoding="utf-8"), "stream-final-review")
            stream_log = tmp_path / "stream-test.stream.jsonl"
            self.assertTrue(stream_log.exists())
            self.assertIn('"content_block_delta"', stream_log.read_text(encoding="utf-8"))

    def test_streaming_run_returns_only_current_stderr_slice(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            counter = tmp_path / "counter.txt"
            fake_claude = tmp_path / "fake_stream_stderr_claude.py"
            fake_claude.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json, pathlib, sys",
                        f"counter = pathlib.Path({str(counter)!r})",
                        "count = int(counter.read_text() or '0') + 1 if counter.exists() else 1",
                        "counter.write_text(str(count))",
                        "sys.stdin.read()",
                        "if count == 1:",
                        "    print('old-stderr-from-first-run', file=sys.stderr)",
                        "print(json.dumps({",
                        "  'type': 'result',",
                        "  'subtype': 'success',",
                        "  'is_error': False,",
                        "  'result': f'stream-result-{count}',",
                        "  'session_id': f'fake-stream-session-{count}',",
                        "  'total_cost_usd': 0",
                        "}), flush=True)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)
            paths = mod.review_paths(tmp_path, "stream-stderr")
            run_args = args(
                claude_bin=str(fake_claude),
                heartbeat_seconds=1,
                timeout_seconds=0,
                stream=True,
            )

            first = mod.run_claude_streaming(
                run_args,
                Path.cwd(),
                "stream-stderr",
                None,
                "Review this.",
                False,
                paths,
            )
            second = mod.run_claude_streaming(
                run_args,
                Path.cwd(),
                "stream-stderr",
                None,
                "Review this again.",
                False,
                paths,
            )

            self.assertIn("old-stderr-from-first-run", first.stderr)
            self.assertNotIn("old-stderr-from-first-run", second.stderr)

    def test_streaming_run_throttles_event_metadata_updates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            fake_claude = tmp_path / "fake_stream_burst_claude.py"
            fake_claude.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json, sys, time",
                        "sys.stdin.read()",
                        "for index in range(20):",
                        "    print(json.dumps({'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': str(index)}}), flush=True)",
                        "    time.sleep(0.005)",
                        "print(json.dumps({",
                        "  'type': 'result',",
                        "  'subtype': 'success',",
                        "  'is_error': False,",
                        "  'result': 'burst-final-review',",
                        "  'session_id': 'fake-burst-session',",
                        "  'total_cost_usd': 0",
                        "}), flush=True)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)
            paths = mod.review_paths(tmp_path, "stream-burst")
            run_args = args(
                claude_bin=str(fake_claude),
                heartbeat_seconds=1,
                timeout_seconds=0,
                stream=True,
            )

            metadata_writes = 0
            event_metadata_writes = 0
            original_update_metadata = mod.update_metadata

            def counting_update_metadata(path, **fields):
                nonlocal metadata_writes, event_metadata_writes
                metadata_writes += 1
                if "last_claude_event_at" in fields:
                    event_metadata_writes += 1
                return original_update_metadata(path, **fields)

            mod.update_metadata = counting_update_metadata
            try:
                with redirect_stdout(io.StringIO()):
                    result = mod.run_claude_streaming(
                        run_args,
                        Path.cwd(),
                        "stream-burst",
                        None,
                        "Review this.",
                        False,
                        paths,
                    )
            finally:
                mod.update_metadata = original_update_metadata

            self.assertEqual(result.returncode, 0)
            self.assertLess(metadata_writes, 10)
            self.assertLess(event_metadata_writes, 21)
            metadata = json.loads((tmp_path / "stream-burst.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["claude_event_count"], 21)
            self.assertEqual(metadata["last_claude_event_type"], "result")

    def test_start_enforces_default_max_rounds_per_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata = Path(tmpdir) / "round-test.json"
            mod.atomic_write_json(
                metadata,
                {
                    "key": "round-test",
                    "session_id": "session-123",
                    "round_index": 3,
                    "status": "done",
                },
            )

            blocked = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "start",
                    "--dry-run",
                    "--key",
                    "round-test",
                    "--store-dir",
                    tmpdir,
                    "--claude-bin",
                    "/bin/false",
                    "--no-diff",
                    "Fourth round.",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("max review rounds", blocked.stderr)

            unbounded = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "start",
                    "--dry-run",
                    "--max-rounds",
                    "0",
                    "--key",
                    "round-test",
                    "--store-dir",
                    tmpdir,
                    "--claude-bin",
                    "/bin/false",
                    "--no-diff",
                    "Fourth round.",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(unbounded.returncode, 0, unbounded.stderr)

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_tmux_background_reuses_runner_window_for_followup_rounds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            tmux_session = f"claude-review-test-runner-{os.getpid()}"
            counter = tmp_path / "counter.txt"
            argv_log = tmp_path / "argv.jsonl"
            fake_claude = tmp_path / "fake_claude.py"
            fake_claude.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json, pathlib, sys",
                        f"counter = pathlib.Path({str(counter)!r})",
                        f"argv_log = pathlib.Path({str(argv_log)!r})",
                        "count = int(counter.read_text() or '0') + 1 if counter.exists() else 1",
                        "counter.write_text(str(count))",
                        "argv_log.write_text(argv_log.read_text() + json.dumps(sys.argv) + '\\n' if argv_log.exists() else json.dumps(sys.argv) + '\\n')",
                        "sys.stdin.read()",
                        "print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': f'fake-runner-review-{count}', 'session_id': 'fake-runner-session', 'total_cost_usd': 0}), flush=True)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)

            base_cmd = [
                sys.executable,
                str(SCRIPT),
                "start",
                "--background",
                "--background-launcher",
                "tmux",
                "--tmux-session",
                tmux_session,
                "--tmux-runner-idle-seconds",
                "30",
                "--key",
                "runner-reuse-test",
                "--store-dir",
                tmpdir,
                "--claude-bin",
                str(fake_claude),
                "--no-diff",
                "--heartbeat-seconds",
                "1",
            ]

            try:
                cleanup_tmux_session(tmux_session)
                first = subprocess.run(
                    [*base_cmd, "Review this."],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(first.returncode, 0, first.stderr)

                wait_first = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "wait",
                        "--key",
                        "runner-reuse-test",
                        "--store-dir",
                        tmpdir,
                        "--poll-seconds",
                        "1",
                        "--timeout-seconds",
                        "5",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(wait_first.returncode, 0, wait_first.stderr)
                first_metadata = json.loads((tmp_path / "runner-reuse-test.json").read_text(encoding="utf-8"))
                self.assertEqual(first_metadata["round_index"], 1)
                self.assertEqual(first_metadata["tmux_window_name"], "review-runner-reuse-test")
                self.assertTrue(tmux_window_exists(first_metadata["tmux_window_id"]))

                second = subprocess.run(
                    [*base_cmd, "Follow up."],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(second.returncode, 0, second.stderr)

                wait_second = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "wait",
                        "--key",
                        "runner-reuse-test",
                        "--store-dir",
                        tmpdir,
                        "--poll-seconds",
                        "1",
                        "--timeout-seconds",
                        "5",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(wait_second.returncode, 0, wait_second.stderr)
                second_metadata = json.loads((tmp_path / "runner-reuse-test.json").read_text(encoding="utf-8"))
                self.assertEqual(second_metadata["round_index"], 2)
                self.assertEqual(second_metadata["tmux_window_id"], first_metadata["tmux_window_id"])
                self.assertEqual(second_metadata["tmux_window_name"], first_metadata["tmux_window_name"])
                self.assertEqual((tmp_path / "runner-reuse-test.findings.md").read_text(encoding="utf-8"), "fake-runner-review-2")

                invocations = [json.loads(line) for line in argv_log.read_text(encoding="utf-8").splitlines()]
                self.assertEqual(len(invocations), 2)
                self.assertNotIn("--resume", invocations[0])
                self.assertIn("--resume", invocations[1])
                self.assertEqual(invocations[1][invocations[1].index("--resume") + 1], "fake-runner-session")

                manager_log = mod.tmux_manager_log_path(Path(tmpdir), tmux_session)
                log_text = manager_log.read_text(encoding="utf-8")
                self.assertEqual(log_text.count("event=opened"), 1)
                self.assertEqual(log_text.count("event=queued"), 2)
                self.assertEqual(log_text.count("event=closed"), 2)
            finally:
                cleanup_tmux_session(tmux_session)

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_background_lifecycle_with_fake_claude_via_tmux(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            tmux_session = f"claude-review-test-bg-{os.getpid()}"
            fake_claude = tmp_path / "fake_claude.py"
            fake_claude.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json, sys, time",
                        "sys.stdin.read()",
                        "time.sleep(0.1)",
                        "print(json.dumps({",
                        "  'type': 'result',",
                        "  'subtype': 'success',",
                        "  'is_error': False,",
                        "  'result': 'fake-review-tmux-ok',",
                        "  'session_id': 'fake-tmux-session',",
                        "  'total_cost_usd': 0",
                        "}))",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)

            try:
                cleanup_tmux_session(tmux_session)
                start = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "start",
                        "--background",
                        "--background-launcher",
                        "tmux",
                        "--tmux-session",
                        tmux_session,
                        "--key",
                        "bg-tmux-test",
                        "--store-dir",
                        tmpdir,
                        "--claude-bin",
                        str(fake_claude),
                        "--no-diff",
                        "--heartbeat-seconds",
                        "1",
                        "Review this.",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(start.returncode, 0, start.stderr)

                wait = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "wait",
                        "--key",
                        "bg-tmux-test",
                        "--store-dir",
                        tmpdir,
                        "--poll-seconds",
                        "1",
                        "--timeout-seconds",
                        "5",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(wait.returncode, 0, wait.stderr)

                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "result",
                        "--key",
                        "bg-tmux-test",
                        "--store-dir",
                        tmpdir,
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "fake-review-tmux-ok")

                metadata = json.loads((tmp_path / "bg-tmux-test.json").read_text(encoding="utf-8"))
                self.assertEqual(metadata["round_index"], 1)
                self.assertEqual(metadata["tmux_session"], tmux_session)
                self.assertIn("tmux_window_id", metadata)
                self.assertIn("tmux_window_name", metadata)
                self.assertNotIn("tmux_socket_name", metadata)
                self.assertTrue(metadata["streaming"])
                self.assertEqual(metadata["claude_event_count"], 1)
                self.assertEqual(metadata["last_claude_event_type"], "result")
                self.assertIsNotNone(metadata["last_claude_event_at"])
                self.assertFalse(metadata["tmux_keep_window"])
                visible = subprocess.run(
                    ["tmux", "has-session", "-t", tmux_session],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(visible.returncode, 0, visible.stderr)
                shell_option = subprocess.run(
                    ["tmux", "show-options", "-t", tmux_session, "default-shell"],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(shell_option.returncode, 0, shell_option.stderr)
                self.assertEqual(shell_option.stdout.strip(), "default-shell /bin/bash")
                self.assertTrue(tmux_window_exists(metadata["tmux_window_id"]))
                names = subprocess.run(
                    ["tmux", "list-windows", "-t", tmux_session, "-F", "#{window_name}"],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(names.returncode, 0, names.stderr)
                self.assertIn(metadata["tmux_window_name"], names.stdout.splitlines())
                manager_log = mod.tmux_manager_log_path(Path(tmpdir), tmux_session)
                log_text = manager_log.read_text(encoding="utf-8")
                self.assertIn("event=opened", log_text)
                self.assertIn("event=closed", log_text)
                self.assertIn("key=bg-tmux-test", log_text)
                self.assertIn("window_name=review-bg-tmux-test", log_text)
            finally:
                cleanup_tmux_session(tmux_session)

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_tmux_background_keep_window_preserves_completed_window(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            tmux_session = f"claude-review-test-keep-{os.getpid()}"
            fake_claude = tmp_path / "fake_claude.py"
            fake_claude.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json, sys",
                        "sys.stdin.read()",
                        "print(json.dumps({",
                        "  'type': 'result',",
                        "  'subtype': 'success',",
                        "  'is_error': False,",
                        "  'result': 'fake-review-keep-ok',",
                        "  'session_id': 'fake-keep-session',",
                        "  'total_cost_usd': 0",
                        "}))",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)

            try:
                cleanup_tmux_session(tmux_session)
                start = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "start",
                        "--background",
                        "--background-launcher",
                        "tmux",
                        "--tmux-session",
                        tmux_session,
                        "--tmux-keep-window",
                        "--key",
                        "keep-test",
                        "--store-dir",
                        tmpdir,
                        "--claude-bin",
                        str(fake_claude),
                        "--no-diff",
                        "Review this.",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(start.returncode, 0, start.stderr)

                wait = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "wait",
                        "--key",
                        "keep-test",
                        "--store-dir",
                        tmpdir,
                        "--poll-seconds",
                        "1",
                        "--timeout-seconds",
                        "5",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(wait.returncode, 0, wait.stderr)

                metadata = json.loads((tmp_path / "keep-test.json").read_text(encoding="utf-8"))
                self.assertTrue(metadata["tmux_keep_window"])
                window = subprocess.run(
                    ["tmux", "has-session", "-t", metadata["tmux_window_id"]],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(window.returncode, 0, window.stderr)
                capture = subprocess.run(
                    ["tmux", "capture-pane", "-pt", metadata["tmux_window_id"], "-S", "-20"],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertIn("Claude review finished with exit=0", capture.stdout)
            finally:
                cleanup_tmux_session(tmux_session)

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_cancel_tmux_background_review_marks_cancelled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            tmux_session = f"claude-review-test-cancel-{os.getpid()}"
            fake_claude = tmp_path / "slow_fake_claude.py"
            fake_claude.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import sys, time",
                        "sys.stdin.read()",
                        "time.sleep(30)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)

            try:
                cleanup_tmux_session(tmux_session)
                start = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "start",
                        "--background",
                        "--background-launcher",
                        "tmux",
                        "--tmux-session",
                        tmux_session,
                        "--key",
                        "cancel-test",
                        "--store-dir",
                        tmpdir,
                        "--claude-bin",
                        str(fake_claude),
                        "--no-diff",
                        "--heartbeat-seconds",
                        "1",
                        "Review this.",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(start.returncode, 0, start.stderr)

                started = json.loads((tmp_path / "cancel-test.json").read_text(encoding="utf-8"))
                self.assertEqual(started["tmux_session"], tmux_session)
                windows = subprocess.run(
                    ["tmux", "list-windows", "-t", tmux_session, "-F", "#{window_name}"],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(windows.returncode, 0, windows.stderr)
                self.assertIn(started["tmux_window_name"], windows.stdout)

                status = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "status",
                        "--key",
                        "cancel-test",
                        "--store-dir",
                        tmpdir,
                        "--json",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(status.returncode, 0, status.stderr)
                running = json.loads(status.stdout)
                self.assertEqual(running["status"], "running")
                self.assertTrue(running["pid_alive"])

                cancel = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "cancel",
                        "--key",
                        "cancel-test",
                        "--store-dir",
                        tmpdir,
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(cancel.returncode, 0, cancel.stderr)

                metadata = json.loads((tmp_path / "cancel-test.json").read_text(encoding="utf-8"))
                self.assertEqual(metadata["status"], "cancelled")
                self.assertIsNotNone(metadata["completed_at"])
                visible = subprocess.run(
                    ["tmux", "has-session", "-t", tmux_session],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(visible.returncode, 0, visible.stderr)
                manager_log = mod.tmux_manager_log_path(Path(tmpdir), tmux_session)
                log_text = manager_log.read_text(encoding="utf-8")
                self.assertIn("event=cancelled", log_text)
                self.assertIn("key=cancel-test", log_text)
            finally:
                cleanup_tmux_session(tmux_session)

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_tmux_background_no_keep_window_closes_completed_window(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            tmux_session = f"claude-review-test-close-{os.getpid()}"
            fake_claude = tmp_path / "fake_claude.py"
            fake_claude.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json, sys",
                        "sys.stdin.read()",
                        "print(json.dumps({",
                        "  'type': 'result',",
                        "  'subtype': 'success',",
                        "  'is_error': False,",
                        "  'result': 'fake-review-close-ok',",
                        "  'session_id': 'fake-close-session',",
                        "  'total_cost_usd': 0",
                        "}))",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)

            try:
                cleanup_tmux_session(tmux_session)
                start = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "start",
                        "--background",
                        "--background-launcher",
                        "tmux",
                        "--tmux-session",
                        tmux_session,
                        "--no-tmux-keep-window",
                        "--tmux-runner-idle-seconds",
                        "0",
                        "--key",
                        "close-test",
                        "--store-dir",
                        tmpdir,
                        "--claude-bin",
                        str(fake_claude),
                        "--no-diff",
                        "Review this.",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(start.returncode, 0, start.stderr)

                wait = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "wait",
                        "--key",
                        "close-test",
                        "--store-dir",
                        tmpdir,
                        "--poll-seconds",
                        "1",
                        "--timeout-seconds",
                        "5",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(wait.returncode, 0, wait.stderr)
                metadata = json.loads((tmp_path / "close-test.json").read_text(encoding="utf-8"))
                self.assertFalse(metadata["tmux_keep_window"])
                self.assertTrue(wait_for_tmux_window_absent(metadata["tmux_window_id"]))

                second = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "start",
                        "--background",
                        "--background-launcher",
                        "tmux",
                        "--tmux-session",
                        tmux_session,
                        "--no-tmux-keep-window",
                        "--tmux-runner-idle-seconds",
                        "0",
                        "--key",
                        "close-test",
                        "--store-dir",
                        tmpdir,
                        "--claude-bin",
                        str(fake_claude),
                        "--no-diff",
                        "Follow up.",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(second.returncode, 0, second.stderr)

                wait_second = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "wait",
                        "--key",
                        "close-test",
                        "--store-dir",
                        tmpdir,
                        "--poll-seconds",
                        "1",
                        "--timeout-seconds",
                        "5",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(wait_second.returncode, 0, wait_second.stderr)
                metadata_second = json.loads((tmp_path / "close-test.json").read_text(encoding="utf-8"))
                self.assertEqual(metadata_second["round_index"], 2)
                self.assertTrue(wait_for_tmux_window_absent(metadata_second["tmux_window_id"]))
            finally:
                cleanup_tmux_session(tmux_session)

    def test_background_dry_run_does_not_create_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dry_run = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "start",
                    "--background",
                    "--dry-run",
                    "--key",
                    "dry-bg",
                    "--store-dir",
                    tmpdir,
                    "--claude-bin",
                    "/bin/false",
                    "--no-diff",
                    "Review this.",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
            payload = json.loads(dry_run.stdout)
            self.assertEqual(payload["key"], "dry-bg")
            self.assertFalse((Path(tmpdir) / "dry-bg.json").exists())

    def test_status_persists_crashed_and_removes_request_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            metadata = tmp_path / "dead-worker.json"
            request = tmp_path / "dead-worker.request.json"
            queue_dir = tmp_path / "dead-worker.queue"
            queue_dir.mkdir()
            queued = queue_dir / "queued.json"
            request.write_text('{"stdin_text":"sensitive diff"}\n', encoding="utf-8")
            queued.write_text('{"stdin_text":"queued diff"}\n', encoding="utf-8")
            mod.atomic_write_json(
                metadata,
                {
                    "key": "dead-worker",
                    "status": "running",
                    "pid": 999999999,
                    "last_heartbeat_at": mod.iso_from_epoch(mod.epoch_seconds() - 120),
                    "heartbeat_interval_seconds": 30,
                    "request_path": str(request),
                    "request_queue_dir": str(queue_dir),
                },
            )

            status = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "status",
                    "--key",
                    "dead-worker",
                    "--store-dir",
                    tmpdir,
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(status.returncode, 1)
            payload = json.loads(status.stdout)
            self.assertEqual(payload["status"], "crashed")
            persisted = json.loads(metadata.read_text(encoding="utf-8"))
            self.assertEqual(persisted["status"], "crashed")
            self.assertFalse(request.exists())
            self.assertEqual(list(queue_dir.iterdir()), [])

    def test_status_persists_stalled_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata = Path(tmpdir) / "stalled-worker.json"
            mod.atomic_write_json(
                metadata,
                {
                    "key": "stalled-worker",
                    "status": "running",
                    "pid": os.getpid(),
                    "last_heartbeat_at": mod.iso_from_epoch(mod.epoch_seconds() - 120),
                    "heartbeat_interval_seconds": 30,
                },
            )

            status = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "status",
                    "--key",
                    "stalled-worker",
                    "--store-dir",
                    tmpdir,
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(status.returncode, 0)
            payload = json.loads(status.stdout)
            self.assertEqual(payload["status"], "stalled")
            persisted = json.loads(metadata.read_text(encoding="utf-8"))
            self.assertEqual(persisted["status"], "stalled")

    def test_status_recovers_persisted_stalled_when_heartbeat_is_fresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata = Path(tmpdir) / "recover-worker.json"
            mod.atomic_write_json(
                metadata,
                {
                    "key": "recover-worker",
                    "status": "stalled",
                    "pid": os.getpid(),
                    "last_heartbeat_at": mod.iso_now(),
                    "heartbeat_interval_seconds": 30,
                },
            )

            status = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "status",
                    "--key",
                    "recover-worker",
                    "--store-dir",
                    tmpdir,
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(status.returncode, 0)
            payload = json.loads(status.stdout)
            self.assertEqual(payload["status"], "running")
            persisted = json.loads(metadata.read_text(encoding="utf-8"))
            self.assertEqual(persisted["status"], "running")

    def test_check_is_nonblocking_and_uses_completion_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            findings = tmp_path / "done.findings.md"
            findings.write_text("done findings", encoding="utf-8")
            mod.atomic_write_json(
                tmp_path / "running-worker.json",
                {
                    "key": "running-worker",
                    "status": "running",
                    "pid": os.getpid(),
                    "last_heartbeat_at": mod.iso_now(),
                    "heartbeat_interval_seconds": 30,
                },
            )
            mod.atomic_write_json(
                tmp_path / "done-worker.json",
                {
                    "key": "done-worker",
                    "status": "done",
                    "findings_path": str(findings),
                },
            )
            mod.atomic_write_json(
                tmp_path / "failed-worker.json",
                {
                    "key": "failed-worker",
                    "status": "failed",
                    "exit_code": 1,
                },
            )

            running = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "check",
                    "--key",
                    "running-worker",
                    "--store-dir",
                    tmpdir,
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            done = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "check",
                    "--key",
                    "done-worker",
                    "--store-dir",
                    tmpdir,
                    "--result",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            failed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "check",
                    "--key",
                    "failed-worker",
                    "--store-dir",
                    tmpdir,
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(running.returncode, 2)
            self.assertEqual(json.loads(running.stdout)["status"], "running")
            self.assertEqual(done.returncode, 0)
            self.assertEqual(done.stdout, "done findings")
            self.assertEqual(failed.returncode, 1)
            self.assertEqual(failed.stdout.strip(), "failed")

    def test_cancel_purges_tmux_request_queue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            queue_dir = tmp_path / "cancel-queued.queue"
            queue_dir.mkdir()
            first = queue_dir / "1.json"
            second = queue_dir / "2.json"
            first.write_text('{"prompt":"first"}\n', encoding="utf-8")
            second.write_text('{"prompt":"second"}\n', encoding="utf-8")
            mod.atomic_write_json(
                tmp_path / "cancel-queued.json",
                {
                    "key": "cancel-queued",
                    "status": "running",
                    "request_path": str(second),
                    "request_queue_dir": str(queue_dir),
                },
            )

            cancel = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "cancel",
                    "--key",
                    "cancel-queued",
                    "--store-dir",
                    tmpdir,
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(cancel.returncode, 0, cancel.stderr)
            self.assertEqual(cancel.stdout.strip(), "cancelled")
            self.assertEqual(list(queue_dir.iterdir()), [])

    def test_cancel_does_not_overwrite_terminal_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            findings = tmp_path / "done.findings.md"
            findings.write_text("review findings", encoding="utf-8")
            mod.atomic_write_json(
                tmp_path / "done.json",
                {
                    "key": "done",
                    "status": "done",
                    "completed_at": "2026-05-14T00:00:00+00:00",
                    "exit_code": 0,
                    "findings_path": str(findings),
                    "session_id": "session-123",
                },
            )

            cancel = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "cancel",
                    "--key",
                    "done",
                    "--store-dir",
                    tmpdir,
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(cancel.returncode, 0, cancel.stderr)
            payload = json.loads(cancel.stdout)
            self.assertEqual(payload["status"], "done")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "result",
                    "--key",
                    "done",
                    "--store-dir",
                    tmpdir,
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "review findings")


if __name__ == "__main__":
    unittest.main()
