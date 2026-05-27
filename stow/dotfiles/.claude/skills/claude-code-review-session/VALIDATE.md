# Validation

Read this file when changing `claude-code-review-session` code, tests, docs, metadata, or behavior.

Before editing skill instructions, consult the available skill-authoring guidance for the current harness:
- `superpowers:writing-skills`
- `skill-creator`
- `write-a-skill`

> Treat those as optional references by skill name, not as required filesystem paths.

Set `skill_dir` to the parent directory of the loaded `SKILL.md`, then run:

```bash
review_script="${skill_dir%/}/scripts/claude_review_session.py"
tests_dir="${skill_dir%/}/tests"

python -m py_compile "$review_script"
python -m unittest discover -s "$tests_dir"
```

If Codex `skill-creator` tooling is available, also run:

```bash
quick_validate.py "$skill_dir"
```

For upstream publication, also verify:
- Directory basename matches the `name` field.
- Frontmatter includes `metadata.author` as `Name <email>`.
- `SKILL.md` stays under 500 lines.
- No `alwaysApply` or `globs` frontmatter fields are present.
- Supporting files use only relative references from the skill directory.
- Scripts avoid `shell=True`, validate paths and inputs, use timeouts for network/process calls, and do not require elevated privileges.
- Content contains no secrets, credentials, real personal data other than `metadata.author`, or hidden instructions that attempt to override agent/system context.

The tests use fake Claude binaries and temporary tmux sessions. They should not require usernames, fixed install roots, active symlinks, network access, or real model access.
