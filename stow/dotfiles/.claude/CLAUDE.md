# Alexis Girault's Agent instructions

## Style

- never use \u2014, only `-`

## Git

- Use my `git cm` alias for committing with a message and signing off.
- Use `gh` for GitHub remote operations.
- Use `glab` for GitLab remote operations.

## Agentic workflow

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
