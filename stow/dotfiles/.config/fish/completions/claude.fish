# Completions for `claude --resume` / `-r`: session titles (or UUIDs when
# untitled), with relative time + first-user-msg hint in the description.
# Backed by ~/.local/bin/claude-session-completions, scoped to the cwd's
# Claude project dir.
complete -c claude -s r -l resume -x -a '(claude-session-completions)'
