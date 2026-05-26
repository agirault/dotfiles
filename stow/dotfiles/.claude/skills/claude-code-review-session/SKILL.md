---
name: claude-code-review-session
description: Use when an agent should ask Claude Code for code review, bug-finding, or a second opinion while preserving a reusable Claude Code session across follow-up requests.
---

# Claude Code Review Session

Use a nested Claude Code process as a persistent reviewer. Prefer the bundled script instead of hand-writing `claude -p` commands; it handles JSON/stream parsing, named session storage, stale-session fallback, prompt-over-stdin, read-only file inspection, and optional git diff capture.

## Quick Start

From the repo being reviewed:

```bash
python ~/.claude/skills/claude-code-review-session/scripts/claude_review_session.py \
  start \
  --key current-work \
  --new \
  --background \
  "Review the current changes for correctness bugs. Findings only."
```

Check status and read findings:

```bash
python ~/.claude/skills/claude-code-review-session/scripts/claude_review_session.py \
  check \
  --json \
  --key current-work

python ~/.claude/skills/claude-code-review-session/scripts/claude_review_session.py \
  result \
  --key current-work
```

Cancel a running review:

```bash
python ~/.claude/skills/claude-code-review-session/scripts/claude_review_session.py \
  cancel \
  --key current-work
```

Foreground use is still supported by omitting `start --background`, but prefer background mode for substantial reviews so the parent can cancel, poll, and recover by key. The script stores metadata, logs, and findings in `~/.claude/review-sessions/`.

## Review Shape

- Use `--mode implementation` for normal code review. This is the default.
- Use `--mode adversarial` for architecture, large refactors, design proposals, migrations, and boundary/invariant reviews.
- Add `--requirements "..."` or `--requirements-file path/to/spec.md` when the reviewer should judge whether the change satisfies a stated ask. Do not ask for spec compliance without providing requirements.
- Add `--system-extra "..."` for one-off reviewer emphasis instead of adding new modes.

Examples:

```bash
python ~/.claude/skills/claude-code-review-session/scripts/claude_review_session.py \
  --key design-review \
  --new \
  --mode adversarial \
  --requirements-file docs/proposal.md \
  "Review this design before implementation."
```

## Workflow

1. Choose a stable `--key` for the workstream, such as branch name, issue id, or `repo-feature`.
2. Use `start --background --new` for the first review unless the caller explicitly wants foreground blocking. By default, the script includes `git status --short` and `git diff HEAD`.
3. Prefer passing relevant files with `--review-path path/to/file` instead of pasting whole files. The default tool policy allows only `Read,Grep,Glob,LS`.
4. Use `check`, `status`, and `result` to monitor and collect findings. Do not infer liveness from vague progress text.
5. Use `cancel --key <key>` instead of trying to interrupt a foreground shell pipeline.
6. Use the same `--key` for follow-ups. Existing sessions resume automatically and do not resend the diff unless `--diff` is passed.
7. Pass `--base origin/main` when reviewing a branch against its merge base target.
8. Pass `--model opus` for complex design reasoning or `--model sonnet` for the default cost/latency balance. Use full model names when reproducibility matters.
9. Pass `--budget <amount>` only when you need a hard spend cap; too-low caps can abort before Claude emits a useful response.
10. Pass `--max-rounds 0` only when the human explicitly wants an unbounded review loop.

## Background Launcher

`--background-launcher auto` is the default. It uses `tmux` when available because managed exec harnesses can kill ordinary child processes after the parent command exits.

By default, background jobs use Claude `stream-json` so the wrapper can record Claude activity separately from wrapper heartbeat. Tmux jobs use the normal tmux server and a single visible manager session named `claude-review`. This makes review activity discoverable with `tmux ls`; attach with `tmux attach -t claude-review`.

Tmux mode uses one lightweight runner window per review key, named `review-<key>`. The runner owns a small request queue for that key, launches `claude -p` for each queued round, streams stdout/stderr into the pane, and appends the same output to durable logs under `~/.claude/review-sessions/`. This keeps a stable window/name across follow-up rounds while preserving structured Claude JSON output for status and results. The persistent `manager` window tails `~/.claude/review-sessions/claude-review.manager.log` and records triggered/queued/opened/reused/closed/cancelled/failed/runner-exit events for audit.

- Use `--tmux-session <name>` to choose a different visible manager session.
- Use `--background-launcher subprocess` only in a normal shell where child processes survive parent exit.
- Use `--background-launcher tmux --tmux-socket-name <name>` only when you intentionally want an isolated tmux server instead of visibility in normal `tmux ls`.
- Use `--tmux-runner-idle-seconds <n>` to control per-key runner persistence after the queue drains. Default is `300`; `0` exits immediately after a round; negative values keep the runner indefinitely.
- Use `--tmux-keep-window` when you explicitly want the per-key runner to stay open indefinitely for manual inspection.
- Use `--no-stream` only when you need the older single-result JSON behavior.
- Use `cancel --key <key>` to kill only that review window; it leaves the manager session and other review windows alone.

## Lifecycle Criteria

The metadata file is `~/.claude/review-sessions/<key>.json`; findings live beside it as `<key>.findings.md`.

- `done`: `status == done`, `exit_code == 0`, and `findings_path` exists.
- `failed`: `status == failed`; inspect stderr log and metadata errors.
- `timeout`: `status == timeout`; the wrapper killed the child Claude process after `--timeout-seconds`.
- `cancelled`: review was explicitly cancelled with `cancel --key`.
- `alive`: `status == running`, heartbeat is fresh, and `pid` is alive.
- `streaming-active`: `claude_activity == streaming-active`; Claude emitted a stream event within the stale threshold.
- `streaming-quiet`: `claude_activity == streaming-quiet`; wrapper/process is alive, but Claude has not emitted a stream event recently. This also reports `status == stalled`.
- `streaming-no-events`: `claude_activity == streaming-no-events`; wrapper/process is alive, but no Claude stream event has been seen yet. If this persists beyond the stale threshold, it also reports `status == stalled`.
- `stalled`: status command reports `stalled`; either the wrapper heartbeat is stale while `pid` is alive, or streaming is enabled and Claude activity is stale.
- `crashed`: status command reports `crashed`; heartbeat is stale and `pid` is dead.

`wait` exits `0` for `done`, `1` for terminal failure states (`failed`, `timeout`, `crashed`, `cancelled`, `missing`), and `2` for `stalled` or wait timeout.

Prefer nonblocking monitoring when the parent agent can do other work:

- `check --key <key> --json`: one-shot completion check. Exits `0` for `done`, `1` for terminal failure or missing metadata, and `2` for running or stalled. It never sleeps.
- `check --key <key> --result`: prints findings and exits `0` if done; otherwise prints status and exits nonzero.
- `status --key <key> --json`: one-shot liveness snapshot. Exits `0` for running, stalled, or done; exits `1` for failure/missing states.
- `wait --key <key>`: blocking sleep loop. Use only when the parent agent is truly blocked on the review result, preferably with a bounded `--timeout-seconds`.

If the calling harness has a loop or scheduled command mechanism, point it at `check --json` or the manager log. The wrapper writes callback-friendly state to the metadata JSON and to `<tmux-session>.manager.log`, but an external process cannot directly wake an already-running LLM turn unless that harness provides its own callback channel.

Streaming metadata:

- `last_heartbeat_at`: wrapper heartbeat. This only proves the wrapper loop is alive.
- `last_claude_event_at`: most recent Claude stream event.
- `last_partial_text_at`: most recent user-visible text delta, when Claude emits one.
- `claude_event_count`: number of parsed Claude stream events.
- `stream_log_path`: raw Claude stream JSONL audit log.

## Context Limits

Do not silently truncate review input. Send complete relevant files or complete diffs whenever feasible. If context must be bounded, prefer narrowing scope with `--path`, a smaller `--base`, or a targeted prompt. If truncation is unavoidable, make it explicit in the prompt and ask Claude for best effort on partial context.

The default child Claude tool policy is read-only: `Read,Grep,Glob,LS`. This allows path-based review without paste-heavy prompts, while still preventing edits, shell commands, nested agents, and skill invocation. Use `--tools none` only when the child must receive all context directly in the prompt.

The wrapper's diff capture uses `--max-diff-bytes` and inserts a visible truncation marker. Use `--max-diff-bytes 0` for no diff truncation, and `--git-timeout-seconds` if git commands are slow or unreliable in the current workspace.

Default diff capture is `git diff HEAD`, which covers uncommitted work. For committed branch review, pass an explicit merge target such as `--base origin/main`.

## Review Loop

Default expectation after invoking this skill:

1. Send the work for review.
2. Read findings and decide which are valid.
3. Address valid findings locally; ignore or rebut invalid findings with a concrete reason.
4. Send a follow-up in the same `--key` session summarizing what changed and any rebuttals.
5. Repeat until Claude reports no actionable findings or only disagreements remain.

The script tracks `round_index` in metadata and blocks rounds above `--max-rounds` (default `3`). If there is still disagreement, summarize both positions and ask the human to choose, unless the human explicitly requested an unbounded review loop and you pass `--max-rounds 0`.

## Validation

After changing the wrapper, run:

```bash
python -m unittest discover -s ~/.claude/skills/claude-code-review-session/tests
```

The tests import the script relative to the skill directory and use a fake Claude binary for background lifecycle coverage, so they do not depend on a username, checkout path, active symlink location, network, or model access.

## Notes

- The child Claude process runs with only read-only file tools by default and slash commands disabled. This prevents edits, shell commands, and recursive skill invocation when Claude Code itself uses this skill.
- The child Claude process runs in the same working directory as the caller. Claude Code transcripts are therefore created under that workspace's Claude project history, while the wrapper's key-to-session files live in `~/.claude/review-sessions/`.
- Child session names are `review-<key>` by default. The script prefixes them with caller context when available (`CLAUDE_SESSION_NAME`, `CLAUDE_CODE_SESSION_NAME`, `CODEX_SESSION_NAME`, `CODEX_THREAD_ID`, or `CLAUDE_SESSION_ID`). Override with `--session-name-prefix` or disable with `--no-session-name-prefix`.
- If a stored session was cleaned up or cannot be resumed, the script starts a fresh session and includes the current diff again.
- For cloud multi-agent review, use Claude Code's built-in `claude ultrareview`; this skill is for local, persistent `claude -p` review threads.
- Run the script with `--help` for all flags.
