# Tmux Setup

## Overview

Tmux is used to manage persistent terminal sessions on remote Linux boxes, accessed via SSH from a Mac. The `cw` fish function provides a workspace abstraction on top of tmux.

## What's configured

### Files

- `~/.tmux.conf` — tmux config (keybindings, mouse, clipboard, status bar)
- `~/.config/fish/config.fish` — SSH agent symlink fix (runs on each login)
- `~/.config/fish/functions/cw.fish` — workspace launcher function

### tmux.conf highlights

- **Prefix:** `Ctrl-a` (instead of default `Ctrl-b`)
- **Mouse:** enabled (click panes, scroll, drag to resize)
- **Splits:** `Ctrl-a \` or `Ctrl-a |` (vertical), `Ctrl-a -` or `Ctrl-a _` (horizontal)
- **Pane navigation:** `Alt+arrow keys` (no prefix needed)
- **New window:** `Ctrl-a c`
- **Reload config:** `Ctrl-a r`
- **Clipboard:** OSC 52 enabled — mouse selections in tmux copy to Mac clipboard (requires iTerm2 setting below)
- **Notifications:** `allow-passthrough` lets OSC 9 escape sequences reach iTerm2 through SSH+tmux. `monitor-bell` + `bell-action any` highlights windows with bell activity in the status bar.

### SSH agent forwarding fix

When you SSH with agent forwarding, the socket path changes on each connection. A symlink at `~/.ssh/ssh_auth_sock` always points to the latest socket. This is updated on each SSH login (in `config.fish`) and tmux is configured to use it (in `.tmux.conf`).

## Mac-side setup (iTerm2)

These are one-time settings on the Mac — not on the remote box.

1. **Clipboard access:** Preferences > General > Selection > check **"Applications in terminal may access clipboard"**
   - This enables OSC 52, so mouse selections in tmux land in the Mac clipboard
   - Fallback: hold **Option** while selecting text to bypass tmux mouse mode, then `Cmd+C` as normal

2. **Notifications:** Preferences > Profiles > Terminal > enable **"Notification Center Alerts"**, then click **"Filter Alerts"** and check **"Send escape sequence-generated alerts"**
   - Also ensure iTerm2 has notification permissions in **System Settings > Notifications**
   - Any program that sends an OSC 9 escape sequence will trigger a macOS notification

## The `cw` command

`cw` (defined in `~/.config/fish/functions/cw.fish`) manages tmux workspaces.

### Usage

```fish
cw              # show picker: list existing workspaces + create new
cw myproject    # create or switch to workspace named "myproject"
```

### What it does

- Each workspace is a tmux **window** with two panes side by side (left + right)
- All workspaces live under a single tmux session called "work"
- When attaching from outside tmux, it creates a **grouped session** so each terminal gets an independent view — you can show different workspaces on different monitors
- The picker uses `fzf` — select an existing workspace or "+ new workspace"
- New workspace names default to the current directory name
- Duplicate names are rejected with a re-prompt

### Multi-monitor workflow

```
# Terminal 1 (monitor 1)
ssh yourhost
cw myproject        # shows myproject

# Terminal 2 (monitor 2)
ssh yourhost
cw other-repo       # shows other-repo independently
```

Both terminals share the same pool of workspaces (visible in the status bar) but each independently chooses which to display.

### Quick reference

| Action | Command |
|---|---|
| New/pick workspace | `cw` |
| Named workspace | `cw name` |
| Switch windows | `Ctrl-a n` / `Ctrl-a p` / `Ctrl-a <number>` |
| Rename window | `Ctrl-a ,` |
| Kill window | `Ctrl-a &` |
| Detach (keep alive) | `Ctrl-a d` |
| Reattach | `cw` (from outside tmux) |
| Add pane | `Ctrl-a \` (vertical) / `Ctrl-a -` (horizontal) |
| Move between panes | `Alt+arrow keys` |

## Dependencies

- `tmux` (installed via apt)
- `fzf` (installed via apt, used by `cw` picker)
- `fish` shell

## Reinstalling from scratch

1. `sudo apt install tmux fzf`
2. The config files above handle the rest — they're already in your dotfiles
