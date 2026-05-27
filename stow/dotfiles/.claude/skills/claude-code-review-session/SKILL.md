---
name: claude-code-review-session
description: Persistent Claude Code review companion for independent code and design critique. Use when an agent needs code review, bug-finding, architecture critique, requirement conformance checks, or iterative follow-up review while preserving reviewer context.
metadata:
  author: Alexis Girault <agirault@nvidia.com>
  tags:
    - claude-code
    - code-review
    - agents
    - tmux
  domain: developer-tools
---

# Claude Code Review Session

Use the bundled script as a persistent, read-only Claude Code reviewer. Resolve `scripts/claude_review_session.py` relative to this skill directory; do not assume the skill is installed under `.claude`, `.agents`, or `.codex`.

For continuous implementation workflows with plan/design/code review gates, use the higher-level `claude-reviewed-development-loop` skill and call this skill as the review primitive.

## Path Setup
When this skill is loaded, set `skill_dir` to the parent directory of the loaded `SKILL.md`, then run:

```bash
review_script="${skill_dir%/}/scripts/claude_review_session.py"
```

Use `$review_script` in commands. Do not locate this skill by searching home-directory roots or assuming a particular agent's install layout.

## Boundary
This is a reviewer companion, not a general-purpose subagent. Default child Claude constraints:
- Persona: code reviewer, bug finder, or design reviewer.
- Tools: `Read,Grep,Glob,LS` only, enforced by the script with `--tools`, `--allowedTools`, and `--permission-mode dontAsk`.
- No edits, shell commands, slash commands, skills, nested agents, or external agents.
- Working directory: same cwd as the caller.

Do not use this skill when the child Claude should implement changes, run commands, mutate files, or operate as an autonomous worker. That needs a separate tool surface with explicit write permissions, sandbox/worktree policy, and cancellation semantics.

## Quick Start
From the repo being reviewed, run:

```bash
python "$review_script" start --key current-work --new --background "Review the current changes for correctness bugs. Findings only."
python "$review_script" check --key current-work --json
python "$review_script" result --key current-work
```

Cancel with `python "$review_script" cancel --key current-work`. Run `python "$review_script" start --help` for all flags.

Foreground use is supported by omitting `--background`, but prefer background mode for substantial reviews so the caller can poll, cancel, and recover by key.

## Review Thread

Use this loop for one persistent Claude review thread. For broader milestone-by-milestone development orchestration, use `claude-reviewed-development-loop`.

1. Choose a stable `--key` for the workstream.
2. Start the first review with `start --background --new`.
3. Prefer `--review-path path/to/file` over pasting whole files; the reviewer can inspect paths with read-only tools.
4. Use `check`, `status`, and `result` for lifecycle state. Do not infer liveness from progress text.
5. Address valid findings locally; ignore or rebut invalid findings with concrete reasons.
6. Send follow-up prompts with the same `--key`; the stored Claude session resumes automatically. Add `--diff` when the follow-up must include fresh git context.
7. Repeat the back-and-forth until Claude reports no actionable findings or only an explicit disagreement remains.

`--max-rounds` defaults to `3`. If disagreement remains at the cap, summarize both positions and ask the human to choose. Use `--max-rounds 0` only when the human explicitly wants an unbounded loop.

## Inputs
- First round includes `git status --short` and `git diff HEAD` unless disabled. Passing `--diff` on the first round is equivalent to the default and does not duplicate the diff. Follow-up rounds omit git context by default because Claude resumes the stored session; pass `--diff` to include current status and diff again.
- Use `--base origin/main`, `--path <pathspec>`, and `--review-path <file-or-dir>` to focus context.
- Use `--requirements "..."` or `--requirements-file spec.md` for requirement conformance checks; do not ask for spec compliance without providing the spec.
- Use `--mode implementation` for normal review, `--mode adversarial` for architecture/migration/risk review, and `--system-extra "..."` for one-off emphasis.
- Use `--model opus` for unusually complex design reasoning; default `sonnet` is the cost/latency balance. Use full model names when reproducibility matters.
- Use `--budget <amount>` only for hard spend caps; too-low caps can abort before useful findings.
- Use `--tools none` only when all review context is supplied directly in the prompt; it disables path inspection.
- Use `--max-diff-bytes 0` for no wrapper diff truncation, and `--git-timeout-seconds <n>` when git context capture is slow or unreliable.
- If context is truncated or narrowed, say so in the prompt and ask Claude for best effort on partial context.

## Background Tmux
`--background-launcher auto` uses tmux when available and falls back to `subprocess` when tmux is unavailable. Use `--background-launcher subprocess` explicitly only in shells where children survive parent exit.

Tmux mode creates a visible manager session, default `claude-review`. Attach with `tmux attach -t claude-review`. Inside it:
- `manager` tails the manager log.
- Each review key gets one lightweight runner window named `review-<key>`.
- The runner owns a per-key queue, launches `claude -p` for each round, streams output into the pane, and appends durable logs.

Useful flags: `--tmux-session <name>`, `--tmux-runner-idle-seconds <n>` (default `300`; `0` exits immediately; negative never exits), `--tmux-keep-window`, and `--tmux-socket-name <name>` only when intentionally hiding from normal `tmux ls`.

Use `--no-stream` only when older single-result JSON behavior is required.

## Lifecycle
Default metadata/log store is `~/.claude/review-sessions/`; override with `--store-dir` when packaging or testing elsewhere. Files include `<key>.json`, `<key>.findings.md`, stdout/stderr logs, stream JSONL, and transient `<key>.queue/`.

Claude Code transcripts use Claude Code's normal project history for the review cwd; wrapper metadata/logs live in `--store-dir`. Child session names default to `review-<key>` and may be prefixed from caller context; override with `--session-name-prefix` or disable with `--no-session-name-prefix` for audit control.

Statuses: `done`, `running`, `stalled`, `failed`, `timeout`, `crashed`, `cancelled`, `missing`.

Command behavior:
- `check --key <key> --json`: one-shot state; exits `0` done, `1` terminal failure/missing, `2` running/stalled.
- `check --key <key> --result`: prints findings when done; otherwise prints status and exits nonzero.
- `result --key <key>`: prints findings only when done; otherwise exits nonzero with an error on stderr.
- `status --key <key> --json`: one-shot liveness; exits `0` for running/stalled/done/cancelled, `1` for failure/missing.
- `wait --key <key>`: blocking loop; exits `0` done, `1` terminal failure/missing, `2` repeated stalled state or wait timeout.
- `cancel --key <key>`: kills only that review key's runner/window or process and purges queued requests.

## Monitoring
Prefer nonblocking monitoring after `start --background`. Use `check --json` in an external timer, harness loop, or callback mechanism when available; use `wait` only when the parent agent cannot do other work.

Polling policy:
- Poll `check --key <key> --json` every 15-30 seconds, or use the harness' scheduled loop feature if one exists.
- `check` is the completion gate: exit `0` means collect `result`, exit `1` means terminal failure/missing/cancelled, exit `2` means keep monitoring or inspect stalled state.
- For `check`, `--json` takes precedence over `--result`; omit `--json` when you want findings printed directly.
- `status` is for liveness diagnostics and dashboards; it intentionally exits `0` for `running`, `stalled`, and `done` so it is not a completion gate.
- If status is `stalled`, inspect `claude_activity`, `heartbeat_age_seconds`, `claude_event_age_seconds`, stderr, and the manager log before cancelling.
- Cancel only when the review is clearly unwanted, the user asked to stop it, the process is `crashed`, or `stalled` persists across at least two polls beyond `stale_after_seconds` with no new Claude events or useful output.

An external timer cannot wake an already-running agent turn unless the harness supports callbacks. If the harness has a `/loop` or equivalent, schedule it to run `check --json` and surface completion, terminal failure, or repeated stalled state.

## Safety
The child Claude runs as the current user in the same cwd. The safety boundary is Claude Code's tool/permission policy, not the parent agent's sandbox. Keep the default read-only policy for review; do not add write or shell tools to this skill. The wrapper disables slash commands to avoid recursion and hidden workflows. If a stored Claude session cannot be resumed, the script starts fresh and includes current diff context again. For cloud-hosted multi-agent review, use `claude ultrareview` if available.

## Validation
When changing this skill, read `VALIDATE.md` and run its checks before claiming completion. See `README.md` for human-facing architecture and upstream packaging notes.
