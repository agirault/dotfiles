#!/usr/bin/env bash
set -euo pipefail

# Apply macOS system preferences.
#
# Every setting here replaces a click in System Settings. macOS protects the
# default browser and the privacy permissions, so you must still approve those
# by hand. See the macOS section of README.md.
#
# This script is safe to run more than once.

if [[ "$(uname -s)" != Darwin ]]; then
    echo "ERROR: macos-defaults.sh must run on macOS."
    exit 1
fi

echo "==> Applying macOS defaults..."

# Close System Settings first. It writes its in-memory copy of the preferences
# on quit, which would overwrite what this script sets.
osascript -e 'tell application "System Settings" to quit' >/dev/null 2>&1 || true

# ---- Trackpad and mouse ----

# Scroll direction: content follows the finger. Turn this off, so that
# scrolling down moves the view down.
defaults write -g com.apple.swipescrolldirection -bool false

# Tap to click, instead of pressing the trackpad down.
defaults write com.apple.AppleMultitouchTrackpad Clicking -bool true
defaults write com.apple.driver.AppleBluetoothMultitouch.trackpad Clicking -bool true
defaults -currentHost write -g com.apple.mouse.tapBehavior -int 1

# Silent clicking: no click sound from the haptic trackpad.
defaults write com.apple.AppleMultitouchTrackpad ActuateDetents -bool false

# Turn off Force Click, so a hard press does not trigger a lookup.
defaults write com.apple.AppleMultitouchTrackpad ForceSuppressed -bool true

# Mouse tracking speed. The macOS default is 3.
defaults write -g com.apple.mouse.scaling -float 1.5

# ---- Screenshots ----

# Save screenshots to a dedicated folder instead of the Desktop.
screenshot_dir="$HOME/Documents/screenshots"
mkdir -p "$screenshot_dir"
defaults write com.apple.screencapture location -string "$screenshot_dir"

# Show where the mouse was clicked in screen recordings.
defaults write com.apple.screencapture showsClicks -bool true

# Countdown in seconds before a screen recording starts.
defaults write com.apple.screencapture captureDelay -int 5

# ---- Appearance ----

# Dark mode. Use osascript, because writing AppleInterfaceStyle directly does
# not tell running applications to redraw.
osascript -e 'tell application "System Events" to tell appearance preferences to set dark mode to true' >/dev/null 2>&1 || true

# ---- Text input ----

# Turn off smart dashes and smart quotes. They corrupt code and commands
# pasted into text fields.
defaults write -g NSAutomaticDashSubstitutionEnabled -bool false
defaults write -g NSAutomaticQuoteSubstitutionEnabled -bool false

# ---- Dock ----

# Hide the Dock until the pointer reaches the screen edge.
defaults write com.apple.dock autohide -bool true

# Icon size, and the larger size used when the pointer is over the Dock.
defaults write com.apple.dock tilesize -int 72
defaults write com.apple.dock magnification -bool true
defaults write com.apple.dock largesize -int 59

# Minimize a window into its own application icon, not into a separate tile.
defaults write com.apple.dock minimize-to-application -bool true

# Bottom-right hot corner starts a Quick Note. 14 is the Quick Note action,
# and modifier 0 means no key needs to be held.
defaults write com.apple.dock wvous-br-corner -int 14
defaults write com.apple.dock wvous-br-modifier -int 0

# Dock contents, in order. dockutil comes from the Brewfile.
# Remove this block if you prefer to arrange the Dock by hand.
if command -v dockutil >/dev/null 2>&1; then
    echo "    Setting Dock contents..."
    dockutil --no-restart --remove all "$HOME" >/dev/null 2>&1 || true
    for app in \
        "/Applications/Slack.app" \
        "/Applications/Firefox.app" \
        "/Applications/Ghostty.app" \
        "/Applications/Microsoft Teams.app" \
        "/System/Applications/Utilities/Activity Monitor.app" \
        "/System/Applications/System Settings.app"
    do
        [[ -d "$app" ]] && dockutil --no-restart --add "$app" "$HOME" >/dev/null 2>&1 || true
    done
    dockutil --no-restart --add "$HOME/Downloads" --view grid --display folder "$HOME" >/dev/null 2>&1 || true
else
    echo "    dockutil not found; skipping Dock contents."
fi

# ---- Finder ----

# Open new windows in column view.
defaults write com.apple.finder FXPreferredViewStyle -string "clmv"

# Desktop icons: hide the internal disk, show anything plugged in.
defaults write com.apple.finder ShowHardDrivesOnDesktop -bool false
defaults write com.apple.finder ShowExternalHardDrivesOnDesktop -bool true
defaults write com.apple.finder ShowRemovableMediaOnDesktop -bool true

# ---- Rectangle ----

# Restore the window-snapping shortcuts and snap areas. Rectangle keeps all of
# its settings in one preferences domain, so an export and import round-trips.
rectangle_plist="$(cd "$(dirname "$0")/.." && pwd)/stow/macos/rectangle.plist"
if [[ -f "$rectangle_plist" ]]; then
    echo "    Importing Rectangle settings..."
    defaults import com.knollsoft.Rectangle "$rectangle_plist"
fi

# ---- Default browser ----

# macOS protects the browser setting, so `defaults write` cannot change it.
# The defaultbrowser tool asks macOS properly, which still shows a dialog that
# you must confirm once.
if command -v defaultbrowser >/dev/null 2>&1 && [[ -d /Applications/Firefox.app ]]; then
    echo "    Setting Firefox as the default browser (confirm the dialog)..."
    defaultbrowser firefox || true
fi

# ---- Restart the affected applications ----

for app in Dock Finder SystemUIServer; do
    killall "$app" >/dev/null 2>&1 || true
done

echo "==> macOS defaults applied."
echo "    Some settings only take effect after you log out and back in."
echo "    Grant Accessibility and Screen Recording permissions by hand, in"
echo "    System Settings > Privacy & Security."
