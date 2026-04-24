# `clr` is an alias for `claude --resume` (see ~/.config/env/env.conf).
# Offers the same session-title/UUID candidates as `claude --resume`.
complete -c clr -x -a '(claude-session-completions)'
