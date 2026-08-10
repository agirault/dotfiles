# Alexis Girault's Agent instructions

## Style

- Never use emdash `—` (U+2014), only hyphen `-` (U+002D)

## Shell

When providing commands for me to run, use the fish syntax if the POSIX alternative isn't compatible. Do stick to Bash for shell scripts.

**No `python3 -c`, inline `jq '...'` with `!`, or `bash -c` with non-trivial quoting.** Claude Code's Bash tool escapes `!` to `\!` in all quoting styles (anthropics/claude-code [#23740](https://github.com/anthropics/claude-code/issues/23740)). `$` and backticks are similarly unsafe.

Instead: Write a script to `$TMPDIR/name.py`, run `python3 $TMPDIR/name.py`.

## Git

- Skip gpg signing
- If precommit causes issues due to sandbox, attempt setting `PRE_COMMIT_HOME` to a path inside the sandbox.
- Use `gh` for GitHub remote operations.
- Use `glab` for GitLab remote operations.
- If Git cannot write the repository metadata:
  - First confirm the failure is a read-only `.git` issue. A normal linked worktree does not fix
    this because its shared refs and administrative files still live under the original `.git`.
  - Use one [`git-shadow`](https://github.com/dmahurin/git-shadow), a writable replacement for the
    repository metadata that keeps the current worktree and borrows the original Git objects. The
    canonical shadow consists of an `.aigit` Git-directory pointer and its `.aigit_` writable
    common directory.
    - If both canonical shadow paths already exist, reuse them. Never rerun the shadow script over an
      existing shadow or create a new shadow for each task or linked worktree.
    - Otherwise, from the main checkout only, run `mk-git-shadow .aigit`. The script expects `.git`
      to be a directory, so do not run it from an existing linked worktree.
    - In the original checkout, direct Git commands through `.aigit`. Create any additional linked
      worktrees from that same shadow so their metadata and shared refs remain under `.aigit_`.
    - Verify the selected repository with `git status`, `git rev-parse --git-dir`,
      `git rev-parse --git-common-dir`, and `git worktree list`. Never commit the generated `.aigit`
      pointer or `.aigit_` directory.
  - Use a writable temporary mirror or clone only when a Git shadow cannot be used. Preserve dirty
    and untracked changes explicitly before switching worktrees.

## Testing

- When adequate, failing test first, fix second.
- Don't overindex on implementation details or values that have no strong guarantee of persisting. Cover the durable contract, based on intended behavior.

## Public messaging

- When commenting on a service (eg: Slack, Gitlab MR, Github issue) with an identify token I own (vs an agent-dedicated token), prepend your agentic name to the message and place the message in a quote like shown below. Exceptions include MR descriptions or messages I am drafting explicitly with you.
```md
<agent-name>:

> <message>
```

## Agentic workflow

### Tools vs Bash

`Bash` is prefered over tools when working on paths within the sandbox. If you need to work outside of the sandbox, avoid using Bash when a dedicated tool can accomplish the task instead:
- **Read** files, not `cat`/`head`/`tail`/`less`
- **Glob** for file lookup, not `find`/`ls`
- **Grep** for content search, not `grep`/`rg`
- **Edit** for modifications, not `sed`/`awk`
- **Write** for file creation, not `echo`/`cat` with redirection

**Exception for file modifications**: `sed`/`awk` (pattern-based and deterministic) may be preferred over
Edit/Write (Inference-based) when determinism is critical or the cost difference is dramatic
(e.g., bulk regex replacements across many files, or surgical edits in large files where reproducing
context from inference is error-prone).
Use this exception only when the user has not requested unattended/no-prompt execution for
the session or task (since Bash might require permission approval).

If you must use Bash, batch commands when possible to reduce the number of permission approval prompts.

### Memory/Rules

Locations:
- This file (personal, global)
- ~/.claude/rules (personal, use-case-specific) -> if you're not Claude, be aware these exist
- CWD's AGENTS.md or CLAUDE.md (project-specific, global)
- CWD's .claude/rules (project-specific, use-case-specific)

> If you're not claude, register the rules under the .claude/ folders by reading their headers (between `---` lines) so you can read these rules when touching paths in their respective scope.

### Skills

When creating skills:
- favor scripting when robustness is high, complexity tolerable, and/or when determinism is critical
- resort to your inference of the one of adequate subagents only when inference is the only way to achieve this without resorting to fragile heuristics

### Superpowers artifacts

- Store Superpowers specs and plans outside repositories under
  `~/superpowers/<project>/{specs,plans}/`.
- Derive `<project>` from the primary Git remote repository name without the
  `.git` suffix. Fall back to the repository-root directory name when no remote
  exists.
- Never create, stage, commit, or leave Superpowers specs or plans under
  `docs/superpowers/` or elsewhere inside a repository.
- Reference artifacts by their absolute external path when handing work to
  another agent. Never copy them into a repository.
