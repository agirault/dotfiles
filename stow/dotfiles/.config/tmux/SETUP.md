# Tmux Setup

## Overview

Tmux is used to manage persistent terminal sessions on remote Linux boxes, accessed via SSH from a Mac.

## What's configured

### tmux.conf highlights

- **Prefix:** `Ctrl-a` (instead of default `Ctrl-b`)
- **Mouse:** enabled (click panes, scroll, drag to resize)
- **Splits:** `Ctrl-a \` or `Ctrl-a |` (vertical), `Ctrl-a -` or `Ctrl-a _` (horizontal)
- **Pane navigation:** `Alt+arrow keys` (no prefix needed)
- **New window:** `Ctrl-a c`
- **Reload config:** `Ctrl-a r`
- **Clipboard:** OSC 52 enabled - mouse selections in tmux copy to Mac clipboard (requires iTerm2 setting below)
- **Notifications:** `allow-passthrough` lets OSC 9 escape sequences reach iTerm2 through SSH+tmux. `monitor-bell` + `bell-action any` highlights windows with bell activity in the status bar.


## Mac-side setup (iTerm2)

These are one-time settings on the Mac - not on the remote box.

1. **Clipboard access:** Preferences > General > Selection > check **"Applications in terminal may access clipboard"**
   - This enables OSC 52, so mouse selections in tmux land in the Mac clipboard
   - Fallback: hold **Option** while selecting text to bypass tmux mouse mode, then `Cmd+C` as normal

2. **Notifications:** Preferences > Profiles > Terminal > enable **"Notification Center Alerts"**, then click **"Filter Alerts"** and check **"Send escape sequence-generated alerts"**
   - Also ensure iTerm2 has notification permissions in **System Settings > Notifications**
   - Any program that sends an OSC 9 escape sequence will trigger a macOS notification

## Reinstalling from scratch

1. `sudo apt install tmux`
2. The config files above handle the rest - they're already in your dotfiles
