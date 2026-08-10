---
name: claude-reviewed-development-loop
description: Use when multi-step implementation needs recurring review, plan adjustment, or milestone quality gates.
license: "Apache-2.0"
metadata:
  author: Alexis Girault <agirault@nvidia.com>
  tags:
    - claude-code
    - implementation
    - code-review
    - workflow
    - agents
  domain: developer-tools
---

# Claude Reviewed Development Loop

Use this as the parent-agent workflow for continuous implementation with recurring Claude review. Use `claude-code-review-session` as the review primitive; this skill decides when to call it and how to close each loop.

## Purpose

Keep multi-step implementation work moving through small verified milestones while repeatedly consulting a persistent Claude reviewer for plan, design, code, and disagreement checks.

Use This Skill When

- The task spans multiple implementation milestones and needs recurring review gates.
- The plan or design may change as review findings arrive.
- You need explicit policy for autonomy, commits, pushes, MR handling, and disagreement deadlocks.
- You want to avoid a large unreviewed bring-up diff by verifying and reviewing each milestone.

Do not use this skill for a single final branch readiness pass, a one-shot code review, or simple MR description cleanup. Stick to `claude-code-review-session` when only one persistent review thread is needed.

## Prerequisites

- `claude-code-review-session` available and loaded before running review commands.
- Git worktree for local decision-log exclusion and diff-based review.
- Test commands or validation steps known for the target project.
- An authenticated API client only when push or MR handling is allowed.

## Flow

### Setup

First, establish policy. Do nothing else first: no setup dirs, exclude edits, review starts, tests, code, commits, pushes, or MRs.

Use structured user-input UI if available; if limited to 3 prompts, combine push+MR and follow up only when pushing is allowed. Otherwise ask once in plain text. Required answers:
- Autonomy: autonomous, or ask before material plan/design changes and unresolved review disagreements?
- Commits: commit verified milestones, or leave uncommitted?
- Pushes: after commits, only when asked, or never?
- MRs: if pushing and no MR exists, create one, ask first, or branch-only?

Record answers in the working plan. Never infer commit or push permission.

If the harness exposes a task-list or plan-tracker UI, create the visible task list immediately after policy is set and before implementation or review work begins. Keep it updated as milestones start, complete, or change. The visible tracker is part of the working plan, not optional narration.

Then load `claude-code-review-session`. Resolve its `scripts/claude_review_session.py` wrapper from that skill's `SKILL.md` location, then choose one stable review key for the workstream unless the work naturally splits into independent branches of review.

Set shell variables and create a local-only decision log before the first nontrivial review:

```bash
review_script="${review_script:?load claude-code-review-session and set review_script first}"
review_key="stable-workstream-key"
first_review_args=(--new)

exclude_file="$(git rev-parse --git-path info/exclude)"
mkdir -p .agent-review-decisions
mkdir -p "$(dirname "$exclude_file")"
grep -qxF ".agent-review-decisions/" "$exclude_file" 2>/dev/null || printf "%s\n" ".agent-review-decisions/" >> "$exclude_file"
decision_log=".agent-review-decisions/${review_key}.md"
```

After the first successful `start` for a key, set `first_review_args=()` so later checkpoints resume the same Claude session. If using multiple review keys, keep separate `review_key`, `first_review_args`, and `decision_log` state for each key. This skill assumes a Git worktree; if `git rev-parse` fails, ask before choosing another local-only decision-log location.

If the review wrapper refuses a follow-up because the key reached its default maximum round count, do not switch keys for the same workstream. Continue the same key only when appropriate by passing an explicit higher `--max-rounds` or `--max-rounds 0`, and record why continuing is still within the same review thread. Use a new key only for genuinely independent branches of review.

Do not stage or commit `.agent-review-decisions/`. It is for local audit of unresolved disagreements, executive decisions, and review-loop rationale.

## Loop

1. Reassess the current plan or task list before each milestone. If recent findings change the plan materially, follow the kickoff autonomy policy: ask the human first in human-gated mode; otherwise update the plan, send it to Claude for review, and commit that plan/list update separately when commits are allowed.
2. For complex or opinionated architecture work, write a succinct design note before implementation. Ask the human first in human-gated mode; otherwise send it to Claude for review.
3. Implement one verified milestone at a time (tests first). Keep diffs small enough to review and revert.
4. Run the relevant tests, and benchmarks when adequate, before asking for code review.
5. Send nontrivial implementation diffs to Claude. Use the same `--key`; pass `--diff` on follow-up rounds when the current diff changed materially.
6. Evaluate Claude's findings. Fix valid issues and rebut invalid ones with concrete evidence. Unless the adjustments are minimal and fully aligned with the review, send the result back to Claude and include your answer to any review point you do not agree with. See [disagreements](#disagreements) for deadlock policy.
7. Stay DRY: tighten the work to reduce obsolete code, AI slop, redundancy, and docs drift. Less is more.
8. Commit each verified milestone only when the kickoff policy and repo instructions allow commits. Do not accumulate a large uncommitted bring-up diff.
9. If pushing is allowed, handle the MR according to the kickoff policy: create one if allowed and none exists, otherwise keep the branch-only workflow.
10. If an MR exists and pushing is allowed, schedule the following task 30-60 seconds after pushes: fetch open review comments with an authenticated API client and fold them into the next plan reassessment. Human MR comments do not need Claude re-review unless they trigger design, scope, or correctness uncertainty.
11. Repeat until the task is complete, aligned with review, and verified.

## Stop Conditions

Stop and ask the human when:
- the next step would violate repo or user instructions,
- tests or benchmarks expose a regression you cannot isolate,
- Claude reports a credible high-impact risk and the fix would change scope,
- review disagreement exceeds the threshold and autonomous mode was not explicitly requested.

## Review With Claude

### Operating Stance

Remember you have this companion for every step, to challenge your assumptions and cover your blind spots.
Work collaboratively and maintain critical thinking and healthy skepticism of its opinions.
Trust that you are both striving for the same goal, as a team, with deep belief in the collaborative process.
Be aware that every request has a cost: while you should not be taking shortcuts, you want to minimize churn,
unnecessary context/token usage, so do not overuse it or feed it more than it needs. Optimize for quality first,
while keeping efficiency in mind. Ask for concise findings when Claude's responses are too verbose.

### Prompt Examples

Plan review:

```bash
python "$review_script" start --key "$review_key" "${first_review_args[@]}" --background --mode adversarial --requirements-file plan.md "Review this implementation plan for missing steps, risky assumptions, and unnecessary scope. Findings only."
```

Design review:

```bash
python "$review_script" start --key "$review_key" "${first_review_args[@]}" --background --mode adversarial --review-path design.md "Review this design before implementation. Challenge architecture, failure modes, and migration risk. Findings only."
```

Code review:

```bash
python "$review_script" start --key "$review_key" "${first_review_args[@]}" --background --diff --base git/ref/to/compare --review-path path/to/changed/file "Review the current implementation diff for correctness regressions and requirement gaps. Findings only."
```

Poll with `check --json`; collect findings with `result`. Prefer asynchronous polling when the harness supports a loop or callback.

### Disagreements

Claude is an independent reviewer, not ground truth. Count only substantive back-and-forth rounds where the parent agent and Claude still disagree after evidence is exchanged.

After 2 disagreement rounds:
- If the user explicitly requested uninterrupted autonomous work, document the disagreement and the executive decision in `$decision_log`, then proceed.
- Otherwise, ask the human to choose. Include both positions, your recommendation, and whether 2 remains the right deadlock threshold.

Decision log entry format:

```markdown
## YYYY-MM-DD HH:MM UTC - <topic>

- Review key:
- Context:
- Claude position:
- Parent-agent position:
- Evidence checked:
- Executive decision:
- Follow-up risk:
```

Keep the decision log factual and short. It records why the agent proceeded despite unresolved disagreement; it is not a substitute for committed design docs or code comments.

## Limitations

- This skill orchestrates the parent agent; it does not grant write, commit, push, or MR permissions.
- Claude review is advisory. The parent agent must verify findings and own final decisions.
- Local decision logs are intentionally uncommitted and can be lost with the worktree.
- MR polling depends on the repository host and available authenticated client.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Review command lacks `$review_script` | `claude-code-review-session` was not loaded first. | Load that skill and set `review_script` from its Path Setup. |
| Decision log path cannot be excluded | Current directory is not a Git worktree. | Ask before choosing another local-only log location. |
| Push or MR step fails | Missing authentication, wrong remote, or user policy disallows it. | Stop and ask; do not infer permission or retry destructively. |
| Claude and parent agent disagree repeatedly | Review loop hit the deadlock threshold. | Document the disagreement in `$decision_log`; ask the human unless autonomous mode was explicit. |
