# Load shared environment from ~/.config/env/env.conf
set -l conf "$HOME/.config/env/env.conf"
test -r "$conf"; or return

set -l section ""
while read -l line
    # Skip comments and empty lines
    string match -qr '^\s*#' -- $line; and continue
    string match -qr '^\s*$' -- $line; and continue

    # Section header
    if string match -qr '^\[(.+)\]$' -- $line
        set section (string match -r '^\[(.+)\]$' -- $line)[2]
        continue
    end

    # Parse KEY=value (key must be a valid identifier)
    set -l parts (string match -r '^([A-Za-z_][A-Za-z0-9_]*)=(.+)$' -- $line)
    test (count $parts) -ge 3; or continue
    set -l key $parts[2]
    set -l val $parts[3]
    # Evaluate shell expressions ($HOME, $(command), etc.)
    set val (eval echo "$val")

    switch $section
        case prepend
            if test "$key" = PATH
                fish_add_path --prepend $val
            else
                set -gx $key $val $$key
            end
        case export
            set -gx $key $val
        case alias
            alias $key $val
    end
end < $conf
