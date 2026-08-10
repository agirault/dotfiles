# Claude Code Review Session

Human-facing inspection notes for the persistent Claude Code reviewer skill. Agent-facing usage lives in `SKILL.md`.

## Inspecting Reviews

Default wrapper state lives in `~/.claude/review-sessions/`.

For a review key such as `current-work`, useful files are:

- `current-work.json` - lifecycle metadata, status, session id, tmux window id, and log paths.
- `current-work.findings.md` - final review text returned by Claude.
- `current-work.stdout.log` and `current-work.stderr.log` - durable process logs.
- `current-work.stream.jsonl` - streaming Claude events when background streaming is enabled.
- `current-work.queue/` - transient queued requests for tmux-backed background rounds.

When tmux is available, background reviews use the normal tmux server by default:

```bash
tmux ls
tmux attach -t claude-review
```

Inside `claude-review`, the `manager` window tails the manager log and each active review key uses a `review-<key>` runner window. Runner windows normally close after their idle timeout; durable logs remain in `~/.claude/review-sessions/`.

Programmatic inspection:

```bash
python scripts/claude_review_session.py check --key current-work --json
python scripts/claude_review_session.py result --key current-work
python scripts/claude_review_session.py cancel --key current-work
```
