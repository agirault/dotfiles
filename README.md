# Personal System Setup

Configuration files, shell tools, and a bootstrap installer for Linux (Ubuntu)
and macOS development machines. Managed with [GNU Stow](https://www.gnu.org/software/stow/).

## Quick start

```bash
git clone https://github.com/agirault/dotfiles.git ~/projects/dotfiles
cd ~/projects/dotfiles
./setup.sh
```

## Modular install

```bash
./setup.sh packages     # system packages, fish, claude CLI
./setup.sh configs      # symlink dotfiles and tools via stow
./setup.sh identity     # git name/email/commit signing key
./setup.sh defaults     # macOS system preferences (macOS only)
./setup.sh unlink       # remove symlinks and restore backups
```

### Flags

```bash
./setup.sh --no-docker all      # skip Docker setup (Linux only)
./setup.sh --no-identity all    # skip identity setup (non-interactive)
./setup.sh --no-defaults all    # skip macOS system preferences
```

### macOS

`setup.sh` reads `uname` and runs the matching package script. On macOS it
installs `setup/Brewfile` with Homebrew, skips the Docker and bwrap sandbox
setup, and runs `setup/macos-defaults.sh` to apply the system preferences.

Two steps stay manual, because macOS protects them:

- **Default browser.** `macos-defaults.sh` calls `defaultbrowser firefox`,
  which opens an approval dialog. Click it.
- **Privacy permissions.** Apps that move windows, record the screen, or use
  the microphone need approval after their first launch. Open System Settings
  → Privacy & Security and enable each app.

## Stow packages

| Package | Target | Contents |
|---------|--------|----------|
| `dotfiles` | `~/` | Git, fish, tmux, bash, claude configs, shared env and login script |
| `tools` | `~/.local/bin/` | Standalone commands: `tm` (tmux workspaces) and `ssh-refresh-agent` |
| `macos` | `~/` | macOS-only configuration, such as the Ghostty terminal config |

Ghostty wraps `ssh` with a shell function that installs its terminfo on the
remote host, so remote shells render correctly instead of failing on an unknown
`xterm-ghostty`. The wrapper does not cover `scp`, `rsync`, or git over ssh; run
`ghostty +ssh` by hand for those.

### What's in `dotfiles`

- **Git**: aliases, delta pager, difftastic, rebase settings. Identity via `[include]` from `~/.gitconfig.local`. Commits are signed with an SSH key.
- **Fish**: shell config, shared env loader
- **Tmux**: Ctrl-a prefix, mouse, splits, OSC52 clipboard, bell notifications
- **SSH**: shared defaults only. Private hosts go in `~/.ssh/config.local`, which this repo does not contain. The shared file includes that path first, so a host there can set its own values, and the `Host *` block last, so it only fills gaps. X11 forwarding belongs in `config.local`, next to the machines that need it.
- **Claude**: Claude Code settings, Catppuccin status line, global agent instructions (CLAUDE.md), hooks:
  - `auto-cleanup-session.py` (SessionEnd) - deletes trivially empty sessions on exit
  - `auto-name-session.py` (Stop) - generates titles for unnamed sessions via Claude haiku after the 2nd assistant turn; lockfile-guarded against races. Runs early so `claude --resume <title>` / tab completion work before you exit.
- **Codex**: portable model, auto-approval, workspace-write sandbox, TUI, public marketplaces/plugins, global instructions (AGENTS.md), and the shared Claude review skills. Authentication, project trust, runtime state, and internal integrations remain local.
- **Bash**: `.bashrc.d/` snippets for env loading and login script sourcing
- **Shared env** (`~/.config/env/`): `env.conf` and `login.sh` used by both bash and fish (see below)

### What's in `tools`

- **`tm`**: tmux workspace manager. Run `tm --help` for usage. Alias: `tml` (list).
- **`ssh-refresh-agent`**: Manual command to fix SSH agent in stale tmux sessions. Run `ssh-refresh-agent` to find a live socket and update the symlink, or `ssh-refresh-agent --check` to test. Called automatically by `pre_env.sh` on shell startup.

### macOS defaults

`./setup.sh defaults` runs `setup/macos-defaults.sh`, which applies the system
preferences that can be scripted: scroll direction, tap to click, the
screenshot folder, dark mode, and the Dock and Finder layout. Each setting is
commented with what it changes.

## Shared environment

`~/.config/env/` contains configuration shared by both bash and fish, avoiding duplication between the two shells.

### `env.conf` - environment data

INI-style config parsed by shell-specific loaders (`env_loader.fish` for fish, `00-env-loader.sh` for bash). Each loader reads the same file but uses native shell APIs to apply it. Changes take effect in the current shell process.

Sections: `[prepend]` (prepend to a variable, supports multiple entries), `[export]` (set and export, supports command substitution), `[default]` (export only if unset or empty - honors parent env), `[alias]` (shell aliases). All use `KEY=value` format. See the file itself for current values.

### `pre_env.sh` / `post_env.sh` - startup hooks

POSIX shell scripts executed by the env loader before and after parsing `env.conf`. Bash sources them, fish runs them via `bash` subprocess.

- `pre_env.sh` - runs before `env.conf`: SSH agent symlink fix (needs the raw `SSH_AUTH_SOCK` before `env.conf` overrides it)
- `post_env.sh` - runs after `env.conf`: system info display via fastfetch

**Important limitation:** since fish runs these as subprocesses, environment changes inside the scripts won't affect the calling fish shell. Only use for side-effect operations. For environment changes, use `env.conf`.

## Identity

Git identity (name, email, SSH signing key) is stored in `~/.gitconfig.local` (gitignored). Created interactively by `./setup.sh identity`. Commit signing uses an SSH key, so the same key that authenticates to the git remote also signs your commits.

On a new machine, copy `~/.ssh/id_ed25519` and `~/.ssh/id_ed25519.pub` across by hand, then add the public key to GitHub twice: once as an Authentication key, and once as a Signing key. GitHub stores them as separate entries.

## Testing

```bash
./run_tests.sh              # run tests in a Docker container
./run_tests.sh --no-docker  # run tests directly on this machine
```

Tests validate configs (symlinks, backups, content) and unlink (restore originals).

## Security

- `.gitignore` excludes secrets, keys, and machine-specific files
- `.githooks/pre-commit` scans staged files for private keys, tokens, and identity data
- `~/.gitconfig.local` (identity), `~/.claude/settings.local.json` (permissions), and `~/.claude/memory/` (agent memory) are never committed

## Future work

- **alias**
  - understand whether it works for commands with multiple components
- **tm**:
  - default window panes with claude & tig
- **Claude CLI**:
  - `claude-cleanup` batch cleanup command (interactive bulk deletion)
  - aliases: `claudec`/`clc` for `claude-cleanup`
- **Claude skills**: `~/.claude/skills/` contains custom skills (e.g., weekly-report, unrewind) that would be useful across machines. Not yet stowed - needs review for internal/work-specific content before including in a public repo.
- **Claude rules**: `~/.claude/rules/` (personal, use-case-specific rules) could also be stowed once reviewed.
- **Docker test fixes**: Make `run_tests.sh` pass end-to-end in containers (see known issues below).
- **setup.sh redundancy**: The configs and unlink phases share nearly identical stow iteration logic. Refactor to reduce duplication.
- **Move custom .bashrc lines to .bashrc.d**: Inspect `~/.bashrc` for custom lines and move them to stowed snippets so `.bashrc` stays vanilla Ubuntu.
- **Alternative tooling**: Investigate replacements or complements to GNU Stow and manual package scripts:
  - [lnko](https://github.com/luanvil/lnko) - Stow-like but with interactive conflict resolution, orphan cleanup, and status command
  - [pdrx](https://github.com/stefan-hacks/pdrx) - Auto-tracks which package manager installed what, enables declarative `pdrx apply` on new machines (could replace manual `packages.sh`)
  - [dotter](https://github.com/SuperCuber/dotter) - Rust-based dotfile manager with templating and per-machine variable substitution (could replace `[include]` + `setup.sh identity` pattern)

## Known issues

- **`snap` in Docker**: `packages-linux.sh` installs `glab` via `snap`, which is unavailable in Docker containers. `run_tests.sh` will fail on this step. Needs a `--no-snap` flag or a runtime check for `snapd`.
- **`claude` CLI install in Docker**: The Claude CLI install script may not work in containers. Same category as above.
- **Nerd Font in Docker**: `fisher-plugins.sh` downloads FiraCode Nerd Font, which is unnecessary in headless/container environments.

## License

[Apache 2.0](LICENSE)
