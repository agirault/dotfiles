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
