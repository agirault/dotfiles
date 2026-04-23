# Alexis Girault's Agent instructions

## Style

- Never use emdash `—` (U+2014), only hyphen `-` (U+002D)

## Shell

My interactive shell is fish, when providing commands for me to run, use the fix syntax if the POSIX alternative isn't compatible. Do stick to Bash for shell scripts.

## Git

## Local

### Committing

My commits are GPG signed, therefore:

**1. Try to commit like so** - non-interactive probe; fail fast if signing cannot work:

```bash
printf "" | gpg2 --clear-sign --no-tty --pinentry-mode error -o /dev/null && git cm "..."
```

Use a normal multiline message inside the closing `"..."` (no heredoc).

**2. Copy/Paste the command below otherwise** - interactive terminal can complete pinentry prompts.

```fish
printf "" | gpg2 --clear-sign && git cm "..."
```

## Remote

- Use `gh` for GitHub remote operations.
- Use `glab` for GitLab remote operations.

## Agentic workflow

### Tools over Bash

When outside of a sandbox, avoid using Bash when a dedicated tool can accomplish the task instead:
- **Read** files, not `cat`/`head`/`tail`/`less`
- **Glob** for file lookup, not `find`/`ls`
- **Grep** for content search, not `grep`/`rg`
- **Edit** for modifications, not `sed`/`awk`
- **Write** for file creation, not `echo`/`cat` with redirection

Bash is only for commands that have no dedicated tool equivalent (e.g., `git`, `docker`, `make`, process management).

**Exception for file modifications**: `sed`/`awk` may be preferred over Edit/Write when
determinism is critical or the cost difference is dramatic (e.g., bulk regex replacements
across many files, or surgical edits in large files where reproducing context from inference
is error-prone). Edit/Write are inference-based - they require reproducing file content from
memory, which is expensive and can drift. `sed`/`awk` are pattern-based and deterministic.
Use this exception only when the user has not requested unattended/no-prompt execution for
the session or task (since Bash might require permission approval).

If you must use Bash, try to batch commands when possible to reduce the number of permission approval prompts.

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

### Learnings

Whenever I correct you, suggest afterwards whether I want that learning to be captured by you so you don't make the same future mistake. Use the choice selector tool with your recommended locations to save this as the first option, from the list above. Don't save is also a valid option which could be the recommended one.
