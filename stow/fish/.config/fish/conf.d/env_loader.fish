# Load shared environment from ~/.config/env/*.env
set -l env_dir "$HOME/.config/env"

for f in $env_dir/*.env
    test -r "$f"; or continue
    while read -l line
        # Skip comments and empty lines
        string match -qr '^\s*#' -- $line; and continue
        string match -qr '^\s*$' -- $line; and continue

        # PATH=value -> prepend to PATH
        if string match -qr '^PATH=(.+)' -- $line
            set -l val (string replace -r '^PATH=' '' -- $line)
            # Expand $HOME
            set val (string replace '$HOME' "$HOME" -- $val)
            fish_add_path --prepend $val

        # ALIAS name=command
        else if string match -qr '^ALIAS (.+)=(.+)' -- $line
            set -l parts (string match -r '^ALIAS (.+)=(.+)' -- $line)
            alias $parts[2] $parts[3]

        # KEY=value -> set -gx KEY value
        else if string match -qr '^([A-Z_]+)=(.+)' -- $line
            set -l parts (string match -r '^([A-Z_]+)=(.+)' -- $line)
            set -l val $parts[3]
            # Handle $(command) substitution
            if string match -qr '^\$\((.+)\)$' -- $val
                set val (eval (string replace -r '^\$\((.+)\)$' '$1' -- $val))
            end
            set -gx $parts[2] $val
        end
    end < $f
end
