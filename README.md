# Personal System Setup

Configuration files, shell tools, and a bootstrap installer for Linux dev machines. Managed with [GNU Stow](https://www.gnu.org/software/stow/).

## Quick start

```bash
git clone https://github.com/agirault/dotfiles.git ~/dotfiles
cd ~/dotfiles
./setup.sh
```

## Modular install

```bash
./setup.sh packages     # system packages, fish, docker, claude CLI
./setup.sh configs      # symlink dotfiles and tools via stow
./setup.sh identity     # git name/email/GPG key
./setup.sh unlink       # remove symlinks and restore backups
```

### Flags

```bash
./setup.sh --no-docker all      # skip Docker setup
./setup.sh --no-identity all    # skip identity setup (non-interactive)
```

## Stow packages

| Package | Target | Contents |
|---------|--------|----------|
| `dotfiles` | `~/` | Git, fish, tmux, bash, claude configs, shared env and login script |
| `tools` | `~/.local/bin/` | Standalone commands: `tm` (tmux workspaces), `claude-sessions` (session browser), `ssh-refresh-agent` |

### What's in `dotfiles`

- **Git**: aliases, delta pager, difftastic, rebase settings. Identity via `[include]` from `~/.gitconfig.local`
- **Fish**: shell config, shared env loader
- **Tmux**: Ctrl-a prefix, mouse, splits, OSC52 clipboard, bell notifications
- **Claude**: Claude Code settings, Catppuccin status line, global agent instructions (CLAUDE.md), SessionEnd hooks:
  - `auto-cleanup-session.py` - deletes trivially empty sessions on exit
  - `auto-name-session.py` - generates titles for unnamed sessions via Claude haiku
- **Bash**: `.bashrc.d/` snippets for env loading and login script sourcing
- **Shared env** (`~/.config/env/`): `env.conf` and `login.sh` used by both bash and fish (see below)

### What's in `tools`

- **`tm`**: tmux workspace manager. Run `tm --help` for usage. Alias: `tml` (list).
- **`claude-sessions`**: Cross-directory Claude Code session browser. Python curses TUI with:
  - Collapsible tree view grouped by directory, with search/filter bar and match highlighting
  - Live preview pane showing conversation history (navigable with arrow keys or mouse scroll)
  - Session metadata columns (time, messages, optional branch via `b`)
  - Actions: Enter to resume, `d` to delete, `r` to rename, `c` to collapse/expand all
  - Uses `claude_utils/index.py` to scan all `~/.claude/projects/` session files
- **`ssh-refresh-agent`**:
Manual command to fix SSH agent in stale tmux sessions. Run `ssh-refresh-agent` to find a live socket and update the symlink, or `ssh-refresh-agent --check` to test. Called automatically by `pre_env.sh` on shell startup.

## Shared environment

`~/.config/env/` contains configuration shared by both bash and fish, avoiding duplication between the two shells.

### `env.conf` - environment data

INI-style config parsed by shell-specific loaders (`env_loader.fish` for fish, `00-env-loader.sh` for bash). Each loader reads the same file but uses native shell APIs to apply it. Changes take effect in the current shell process.

Sections: `[prepend]` (prepend to a variable, supports multiple entries), `[export]` (set and export, supports command substitution), `[alias]` (shell aliases). All use `KEY=value` format. See the file itself for current values.

### `pre_env.sh` / `post_env.sh` - startup hooks

POSIX shell scripts executed by the env loader before and after parsing `env.conf`. Bash sources them, fish runs them via `bash` subprocess.

- `pre_env.sh` - runs before `env.conf`: SSH agent symlink fix (needs the raw `SSH_AUTH_SOCK` before `env.conf` overrides it)
- `post_env.sh` - runs after `env.conf`: system info display via fastfetch

**Important limitation:** since fish runs these as subprocesses, environment changes inside the scripts won't affect the calling fish shell. Only use for side-effect operations. For environment changes, use `env.conf`.

## Identity

Git identity (name, email, GPG signing key) is stored in `~/.gitconfig.local` (gitignored). Created interactively by `./setup.sh identity`.

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

- **GPG signing**
  - change default agent lock timing
  - util/tool for unlocking
  - sharing key safely across systems with this repo (see git-crypt & git-secret)
- password mngmt
  - see https://medium.com/@chasinglogic/the-definitive-guide-to-password-store-c337a8f023a1 ?
- **alias**
  - understand whether it works for commands with multiple components
- **tm**:
  - default window panes with claude & tig
- **Claude CLI**:
  - `claude-cleanup` batch cleanup command (interactive bulk deletion)
  - aliases: `claudes`/`cls` for `claude-sessions`, `claudec`/`clc` for `claude-cleanup`
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

- **`snap` in Docker**: `packages.sh` installs `glab` via `snap`, which is unavailable in Docker containers. `run_tests.sh` will fail on this step. Needs a `--no-snap` flag or a runtime check for `snapd`.
- **`claude` CLI install in Docker**: The Claude CLI install script may not work in containers. Same category as above.
- **Nerd Font in Docker**: `fisher-plugins.sh` downloads FiraCode Nerd Font, which is unnecessary in headless/container environments.

## License

[Apache 2.0](LICENSE)
