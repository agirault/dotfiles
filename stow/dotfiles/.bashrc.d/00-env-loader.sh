# Load shared environment from ~/.config/env/
env_dir="$HOME/.config/env"

# Pre-env hook: runs before env.conf (e.g., SSH agent symlink fix)
[ -r "$env_dir/pre_env.sh" ] && . "$env_dir/pre_env.sh"

# Parse env.conf
conf="$env_dir/env.conf"
if [ -r "$conf" ]; then
    section=""
    while IFS= read -r line; do
        # Skip comments and empty lines
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line// /}" ]] && continue

        # Section header
        if [[ "$line" =~ ^\[(.+)\]$ ]]; then
            section="${BASH_REMATCH[1]}"
            continue
        fi

        # Parse KEY=value (key must be a valid identifier)
        [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.+)$ ]] || continue
        key="${BASH_REMATCH[1]}"
        val="${BASH_REMATCH[2]}"

        case "$section" in
            prepend)
                eval val="\"$val\""
                current="${!key}"
                if [ -n "$current" ]; then
                    export "$key=$val:$current"
                else
                    export "$key=$val"
                fi
                ;;
            export)
                eval export "$key=\"$val\""
                ;;
            default)
                # Only set if unset or empty (matches ${VAR:-val} semantics)
                if [ -z "${!key}" ]; then
                    eval export "$key=\"$val\""
                fi
                ;;
            alias)
                alias "$key=$val"
                ;;
        esac
    done < "$conf"
fi

# Post-env hook: runs after env.conf (e.g., fastfetch)
[ -r "$env_dir/post_env.sh" ] && . "$env_dir/post_env.sh"
