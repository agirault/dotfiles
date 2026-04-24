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
- **Focus events:** `focus-events on` forwards terminal focus-gained/lost events to programs inside tmux, so apps can tell whether a pane is actually being watched.


## Mac-side setup (iTerm2)

These are one-time settings on the Mac - not on the remote box.

1. **Clipboard access:** Preferences > General > Selection > check **"Applications in terminal may access clipboard"**
   - This enables OSC 52, so mouse selections in tmux land in the Mac clipboard
   - Fallback: hold **Option** while selecting text to bypass tmux mouse mode, then `Cmd+C` as normal

2. **Notifications:** Preferences > Profiles > Terminal > enable **"Notification Center Alerts"**, then click **"Filter Alerts"** and check **"Send escape sequence-generated alerts"**
   - Also ensure iTerm2 has notification permissions in **System Settings > Notifications**
   - Any program that sends an OSC 9 escape sequence will trigger a macOS notification

3. **Native tabs for tmux windows (`tmux -CC`):** iTerm2 can render each tmux window as a native iTerm2 tab. The `tm` script enables this automatically when it detects `LC_TERMINAL=iTerm2`.
   - **Requires SSH env forwarding**, otherwise `LC_TERMINAL` isn't visible on the remote box:
     - Mac `~/.ssh/config`: `SendEnv LC_TERMINAL LC_TERMINAL_VERSION`
     - Linux `/etc/ssh/sshd_config`: `AcceptEnv LC_TERMINAL LC_TERMINAL_VERSION` (needs root + `sudo systemctl restart ssh`)
   - Without forwarding, `tm` silently falls back to regular tmux attach - everything still works.
   - In `-CC` mode: mouse/scrollback are handled natively by iTerm2 (scrollback is per-tab, not tmux's buffer). SSH drop closes the native tabs but the tmux session keeps running - just reattach.

4. **Tab titles track tmux window names (`tmux -CC`):** out of the box, iTerm2 shows the foreground job or cwd in the tab bar instead of the tmux window name. To fix, create a dedicated profile for tmux:
   - Preferences > General > tmux > check **"Use tmux profile rather than profile of the connecting session"**, and pick a profile (e.g. `tmux`).
   - In that profile, under **General > Title**: the built-in Title dropdown doesn't expose the tmux window name, but the **Subtitle** field accepts interpolated strings. Set it to `\(tab.tmuxWindowName)`.
   - Under **Terminal**: uncheck **"Applications in terminal may change the window name"** so shell prompt escapes (OSC 0/2) can't overwrite the Name.
   - Tmux-side `allow-rename off` + `automatic-rename off` (already in `.tmux.conf`) keep the window name stable once `tm` sets it.

## Reinstalling from scratch

1. `sudo apt install tmux`
2. The config files above handle the rest - they're already in your dotfiles
