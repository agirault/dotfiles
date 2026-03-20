# dotfiles

Personal configuration files for Linux dev machines, managed with [GNU Stow](https://www.gnu.org/software/stow/).

## Quick start

```bash
git clone https://github.com/agirault/dotfiles.git ~/dotfiles
cd ~/dotfiles
./install.sh
```

## Modular install

```bash
./install.sh packages     # system packages, fish, docker, claude CLI
./install.sh configs      # symlink configs via stow
./install.sh identity     # git name/email/GPG key
./install.sh uninstall    # remove symlinks and restore backups
```

### Flags

```bash
./install.sh --no-docker all      # skip Docker setup
./install.sh --no-identity all    # skip identity setup (non-interactive)
```

## Stow packages

| Package | Contents |
|---------|----------|
| `git` | Aliases, delta pager, difftastic, rebase settings. Identity via `[include]` from `~/.gitconfig.local` |
| `fish` | Shell config, SSH agent forwarding fix for tmux, shared env loader |
| `tools` | Standalone commands in `~/.local/bin/`: `cw` tmux workspace manager (run `cw --help`) |
| `tmux` | Ctrl-a prefix, mouse, splits (`\`/`-`), OSC52 clipboard, bell notifications, setup docs |
| `claude` | Claude Code settings, Catppuccin status line, global agent instructions (CLAUDE.md) |
| `bash` | `.bashrc.d/` snippets: shared env loader, fastfetch |
| `env` | Shared environment (PATH, aliases, exports) loaded by both bash and fish |

## Shared environment

`~/.config/env/*.env` files are sourced by both bash and fish via shell-specific loaders. Supported formats:

```
# Comments
PATH=/some/path          # prepended to PATH
ALIAS name=command       # creates a shell alias
KEY=value                # exported as environment variable
KEY=$(command)           # command substitution
```

## Identity

Git identity (name, email, GPG signing key) is stored in `~/.gitconfig.local` (gitignored). Created interactively by `./install.sh identity`.

## Testing

```bash
./run_tests.sh              # run tests in a Docker container
./run_tests.sh --no-docker  # run tests directly on this machine
```

Tests validate install (symlinks, backups, content) and uninstall (restore originals).

## Security

- `.gitignore` excludes secrets, keys, and machine-specific files
- `.githooks/pre-commit` scans staged files for private keys, tokens, and identity data
- `~/.gitconfig.local` (identity), `~/.claude/settings.local.json` (permissions), and `~/.claude/memory/` (agent memory) are never committed

## Future work

- **Claude skills**: `~/.claude/skills/` contains custom skills (e.g., weekly-report, unrewind) that would be useful across machines. Not yet stowed - needs review for internal/work-specific content before including in a public repo.
- **Claude rules**: `~/.claude/rules/` (personal, use-case-specific rules) could also be stowed once reviewed.
- **Docker test fixes**: Make `run_tests.sh` pass end-to-end in containers (see known issues below).
- **Alternative tooling**: Investigate replacements or complements to GNU Stow and manual package scripts:
  - [lnko](https://github.com/luanvil/lnko) - Stow-like but with interactive conflict resolution, orphan cleanup, and status command
  - [pdrx](https://github.com/stefan-hacks/pdrx) - Auto-tracks which package manager installed what, enables declarative `pdrx apply` on new machines (could replace manual `packages.sh`)
  - [dotter](https://github.com/SuperCuber/dotter) - Rust-based dotfile manager with templating and per-machine variable substitution (could replace `[include]` + `install.sh identity` pattern)

## Known issues

- **`snap` in Docker**: `packages.sh` installs `glab` via `snap`, which is unavailable in Docker containers. `run_tests.sh` will fail on this step. Needs a `--no-snap` flag or a runtime check for `snapd`.
- **`claude` CLI install in Docker**: The Claude CLI install script may not work in containers. Same category as above.
- **Nerd Font in Docker**: `fisher-plugins.sh` downloads FiraCode Nerd Font, which is unnecessary in headless/container environments.

## License

[Apache 2.0](LICENSE)
