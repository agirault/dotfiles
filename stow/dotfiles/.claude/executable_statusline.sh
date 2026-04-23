#!/bin/bash

command -v jq >/dev/null || { echo "jq required"; exit 1; }

# Read JSON input from stdin
input=$(cat)

# Extract fields without eval
cwd=$(echo "$input" | jq -r '.workspace.current_dir // empty')
model=$(echo "$input" | jq -r '.model.display_name // empty')
output_style=$(echo "$input" | jq -r '.output_style.name // empty')
used=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
session_cost=$(echo "$input" | jq -r '.cost.total_cost_usd // 0')
session_id=$(echo "$input" | jq -r '.session_id // empty')

# Strip terminal control characters from untrusted display text.
sanitize_for_terminal() {
    printf '%s' "$1" | tr -d '\000-\037\177'
}

# Accumulate cost across sessions (this should be concurrent-safe and should reset monthly
COST_DIR="$HOME/.claude/session_costs"
current_month=$(date +%Y-%m)

mkdir -p "$COST_DIR"

# Clean up old months (runs once per month)
CLEANUP_MARKER="$COST_DIR/.cleaned_${current_month}"
if [ ! -f "$CLEANUP_MARKER" ]; then
    for f in "$COST_DIR"/[0-9][0-9][0-9][0-9]-[0-9][0-9]_*; do
        [ -f "$f" ] || continue
        file_name=$(basename "$f")
        file_month=${file_name%%_*}
        [ "$file_month" != "$current_month" ] && rm -f "$f"
    done
    touch "$CLEANUP_MARKER"
fi

# Write current session's cost to a per-session file (keyed by sanitized session_id)
safe_session_id=$(printf '%s' "$session_id" | tr -c 'A-Za-z0-9._-' '_')
if [ -n "$safe_session_id" ]; then
    echo "$session_cost" > "$COST_DIR/${current_month}_${safe_session_id}"
else
    echo "$session_cost" > "$COST_DIR/${current_month}_${PPID}"
fi

# Sum all session cost files for the current month
files=("$COST_DIR/${current_month}_"*)
if [ -e "${files[0]}" ]; then
    monthly_cost=$(awk 'BEGIN{t=0}{t+=$1}END{printf "%.4f",t}' "${files[@]}")
else
    monthly_cost="0.0000"
fi
# ANSI foreground colors
BOLD="\033[1m"
DIM="\033[2m"
GREEN="\033[32m"
YELLOW="\033[33m"
CYAN="\033[36m"
MAGENTA="\033[35m"
RED="\033[31m"
RESET="\033[0m"

# Build status line
output=""

# Current directory
dir_name=$(basename "$cwd")
safe_dir_name=$(sanitize_for_terminal "$dir_name")
output+=$(printf "${GREEN}%s${RESET}" "$safe_dir_name")

# Git branch if in git repo
if git -C "$cwd" rev-parse --git-dir > /dev/null 2>&1; then
    branch=$(git -C "$cwd" --no-optional-locks branch --show-current 2>/dev/null || echo "detached")
    safe_branch=$(sanitize_for_terminal "$branch")
    output+=$(printf " ${DIM}│${RESET} ${CYAN}%s${RESET}" "$safe_branch")
fi

# Model info
safe_model=$(sanitize_for_terminal "$model")
output+=$(printf " ${DIM}│${RESET} ${YELLOW}%s${RESET}" "$safe_model")

# Context used (color-coded by usage)
if [ -n "$used" ]; then
    used_int=${used%.*}
    if [ "$used_int" -lt 50 ] 2>/dev/null; then
        ctx_color="$GREEN"
    elif [ "$used_int" -lt 80 ] 2>/dev/null; then
        ctx_color="$YELLOW"
    else
        ctx_color="$RED"
    fi
    safe_used=$(sanitize_for_terminal "$used")
    output+=$(printf " ${DIM}│${RESET} ${ctx_color}%s%% used${RESET}" "$safe_used")
fi

# Cost: session | monthly total
output+=$(printf " ${DIM}│${RESET} ${MAGENTA}\$%.2f${RESET}${DIM}/${RESET}${BOLD}\033[38;5;246m\$%.2f${RESET}" "$session_cost" "$monthly_cost")

# Output style (if not default)
if [ -n "$output_style" ] && [ "$output_style" != "default" ]; then
    safe_output_style=$(sanitize_for_terminal "$output_style")
    output+=$(printf " ${DIM}│${RESET} ${CYAN}%s${RESET}" "$safe_output_style")
fi

printf "%s" "$output"
