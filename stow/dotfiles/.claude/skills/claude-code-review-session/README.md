# Claude Code Review Session

Persistent, read-only Claude Code reviewer for agent workflows.

This skill lets an agent ask Claude Code for an independent review, keep reviewer context across follow-up rounds, and expose the work through structured metadata plus visible tmux windows.

## Scope

This is a reviewer companion, not a general-purpose subagent runner.

It is intentionally narrow:

- Local `claude -p` wrapper with JSON or `stream-json` output.
- Persistent review keys and Claude session IDs for follow-up rounds.
- Read-only Claude Code tools: `Read,Grep,Glob,LS`.
- No edits, shell commands, slash commands, skills, nested agents, or external agents.
- Tmux-backed auditability: one manager session and one lightweight runner window per review key.

General implementation work should be a separate skill or tool. A write-capable companion needs a different permission model, sandbox or worktree policy, and explicit tests for writes, shell commands, cancellation, and cleanup.

Docs and tests should not assume an install root such as `.claude`, `.agents`, or `.codex`; use `<skill-dir>` or paths relative to the repository under test.

## Architecture

```text
agent
  -> SKILL.md guidance
  -> scripts/claude_review_session.py
      -> claude -p reviewer process
      -> ~/.claude/review-sessions/ metadata, logs, findings, queues
      -> optional tmux session: claude-review
```

The tmux runner is only a durable control and inspection surface. Claude still runs through `claude -p`, so the wrapper can parse structured output and maintain reliable lifecycle state.
