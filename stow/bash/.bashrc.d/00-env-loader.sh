# Load shared environment from ~/.config/env/*.env
env_dir="$HOME/.config/env"

for f in "$env_dir"/*.env; do
    [ -r "$f" ] || continue
    while IFS= read -r line; do
        # Skip comments and empty lines
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line// /}" ]] && continue

        # PATH=value -> prepend to PATH
        if [[ "$line" =~ ^PATH=(.+) ]]; then
            val="${BASH_REMATCH[1]}"
            eval val="$val"  # expand $HOME
            PATH="$val:$PATH"

        # ALIAS name=command
        elif [[ "$line" =~ ^ALIAS\ (.+)=(.+) ]]; then
            alias "${BASH_REMATCH[1]}=${BASH_REMATCH[2]}"

        # KEY=value -> export KEY=value
        elif [[ "$line" =~ ^([A-Z_]+)=(.+) ]]; then
            key="${BASH_REMATCH[1]}"
            val="${BASH_REMATCH[2]}"
            eval export "$key=$val"
        fi
    done < "$f"
done
export PATH

# Source shared login script (POSIX, shared with fish)
login_script="$env_dir/login.sh"
[ -r "$login_script" ] && . "$login_script"
