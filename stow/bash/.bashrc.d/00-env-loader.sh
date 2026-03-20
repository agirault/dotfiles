# Load shared environment from ~/.config/env/env.conf
conf="$HOME/.config/env/env.conf"
[ -r "$conf" ] || return 0

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
        alias)
            alias "$key=$val"
            ;;
    esac
done < "$conf"

# Source shared login script
login_script="$HOME/.config/env/login.sh"
[ -r "$login_script" ] && . "$login_script"
