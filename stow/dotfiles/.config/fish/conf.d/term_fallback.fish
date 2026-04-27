# Downgrade $TERM when its terminfo entry is missing on this host (e.g.
# SSH'ing in from a Ghostty client, which advertises xterm-ghostty). tmux
# refuses to start under an unknown outer TERM, so this keeps tmux/vim/less
# usable. Inside tmux, $TERM is overridden by tmux's default-terminal
# option, so this only changes how outer apps see the terminal.

status is-interactive; or return
infocmp $TERM >/dev/null 2>&1; and return

set -l missing $TERM
set -gx TERM xterm-256color

set -l y (set_color yellow); set -l b (set_color brblack); set -l n (set_color normal)
echo $y"warning:"$n" no terminfo for '$missing' on "(hostname)"; \$TERM downgraded to $TERM" >&2
echo $b"  to install the proper entry (one-time), run from the $missing client:" >&2
echo "    infocmp -x $missing | ssh "(whoami)"@"(hostname)" -- tic -x -" >&2
echo "  then reconnect."$n >&2
