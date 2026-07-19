# cmd-find

**Fuzzy-find templated shell commands and paste them straight into your terminal.**

You know the command exists, you just can't remember the exact flags. `cmd-find` lets you curate a personal library of shell one-liners in simple `.sh` files, then fuzzy-search them by description and drop the result onto your command line with one keystroke.

![](https://img.shields.io/badge/python-3.8+-blue)
![](https://img.shields.io/badge/platform-linux%20|%20macOS-lightgrey)

---

## Table of contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Usage](#usage)
  - [Shell integration (recommended)](#shell-integration-recommended)
  - [Adding commands](#adding-commands)
  - [Deleting commands](#deleting-commands)
  - [Standalone mode](#standalone-mode)
  - [CLI reference](#cli-reference)
- [Writing command files](#writing-command-files)
  - [Parameterised commands (arguments)](#parameterised-commands-arguments)
- [Configuration](#configuration)
- [How it works](#how-it-works)
  - [Architecture](#architecture)
  - [Fuzzy finder](#fuzzy-finder)
  - [Shell integration](#shell-integration)

---

## Installation

```bash
# Clone or copy the project, then:

cd cmd-find

# Recommended: uv (isolated venv, one command)
uv tool install --editable .

# Or use pip directly
pip install --user -e .

# One-shot: the installer script does everything above
./install.sh
```

The installer will:
1. Install the `cmd-find` command globally (via `uv tool install` or `pip` as fallback)
2. Create a default config at `~/.config/cmd-find/config.toml`
3. Copy example commands to `~/.local/share/cmd-find/commands/`

No system packages are modified. No external dependencies — fzf is optional (the tool ships with its own built-in fuzzy finder).

**Switching from pip to uv?** Just run:

```bash
pip uninstall cmd-find -y
uv tool install --editable .
```

---

## Quick start

```bash
# 1. Create your first command template
mkdir -p ~/.local/share/cmd-find/commands/git

cat > ~/.local/share/cmd-find/commands/git/amend-author.sh << 'EOF'
# Amend the author of the last commit
# Tags: git, fix
git commit --amend --author="New Name <email@example.com>"
EOF

# 2. Fuzzy-find and execute
cmd-find --exec

# 3. Or just print it (for shell integration)
cmd-find
```

Type `amend` or `author` to narrow the list, press Enter — the command is printed (or executed with `--exec`).

---

## Usage

### Shell integration (recommended)

Add **one** of these lines to your shell rc file, then open a new terminal:

```bash
# Bash — add to ~/.bashrc
source /path/to/cmd-find/shell/cmd-find.bash

# Zsh  — add to ~/.zshrc
source /path/to/cmd-find/shell/cmd-find.zsh
```

Now press **Ctrl+F** anywhere on the command line. The fuzzy finder opens. Type to filter, arrow keys to navigate, Enter to select. The command is pasted **at your cursor** — edit it further or press Enter to run.

```
$ echo "before" █                    # Press Ctrl+F
  ┌─ cmd-find ──────────────────────────┐
  │  query: git reb                     │
  │──────────────────────────────────────│
  │> [git,rebase] Interactively...      │
  │  [git,log]    Show a compact...     │
  │                                      │
  │  ↑↓ nav  │ type filter  │ Ctrl+N new │
  └──────────────────────────────────────┘
$ git rebase -i HEAD~3█echo "before"   # Command inserted at cursor
```

### Adding commands

**From scratch (Ctrl+N)** — opens a 3-field form where you type the description, tags, and command. Saved as a `.sh` file in your first configured directory.

```
  New command
──────────────────────────────────────────
> Description:  Amend last commit auth▌
  Tags:         git, fix
  Command:      git commit --amend --author="..."
──────────────────────────────────────────
  Tab: next  │  Enter: save  │  Esc: cancel
```

**From shell history (Ctrl+H)** — searches your `~/.bash_history` or `~/.zsh_history`. Fuzzy-find any past command, then add a description and tags to save it as a reusable template.

```
  History                              (3/427)
──────────────────────────────────────────
> git rebase -i HEAD~3
  docker exec -it web /bin/bash
  find . -name "*.py" | xargs wc -l
──────────────────────────────────────────
  git rebase -i HEAD~3
──────────────────────────────────────────
  ↑↓ nav  │  type filter  │  Enter pick  │  Esc back
```

After picking a history entry, you're prompted for a description and tags — then it's saved just like Ctrl+N.

### Deleting commands

Press **Ctrl+D** on any command to delete its `.sh` file permanently (with a confirmation prompt).

### Standalone mode

```bash
# Fuzzy-find and print the command to stdout
cmd-find
# → git rebase -i HEAD~3

# Narrow down by path — only show commands under a git/ directory
cmd-find git
cmd-find docker

# Fuzzy-find and copy to clipboard
cmd-find --copy

# Fuzzy-find and execute immediately (no shell integration needed)
cmd-find --exec

# List all commands without interactive mode
cmd-find --list
```

### CLI reference

```
cmd-find [-h] [-c CONFIG] [--init] [--list] [--exec] [--copy] [filter]

Options:
  -h, --help            Show help
  -c, --config PATH     Path to config file (default: ~/.config/cmd-find/config.toml)
  --init                Create a default config and commands directory, then exit
  --list                Print all discovered commands (no interactive mode)
  --exec                Execute the selected command via $SHELL (otherwise print it)
  --copy                Copy the selected command to the system clipboard
  filter                Optional positional — only show commands from paths
                        containing this string (e.g. 'git', 'docker', 'ssh')
```

---

## Writing command files

Each command lives in a `.sh` file anywhere inside a configured directory. The file format is simple:

```
# One or more comment lines describe the command.
# They are joined together into a single description string.
# Tags: category1, category2
the actual one-liner shell command
```

### Rules

| Element | Behaviour |
|---|---|
| `# description` | Collected into the description shown in the finder. Multiple lines are joined with spaces. |
| `# Tags: foo, bar` | Special comment. Tags appear as `[foo,bar]` badges and are included in the fuzzy-search text. |
| First non-comment, non-empty line | **This is the command.** Everything after it is ignored — one command per file. |
| Filename | Used as a fallback description if no comment lines are present. |

### Examples

```bash
# ── ~/.local/share/cmd-find/commands/git/undo-commit.sh ──
# Undo the last commit, keeping all changes staged
# Tags: git, undo
git reset --soft HEAD~1
```

```bash
# ── ~/.local/share/cmd-find/commands/docker/cleanup.sh ──
# Remove all stopped containers, unused images, and dangling volumes
# Tags: docker, cleanup
docker system prune -af --volumes
```

```bash
# ── ~/.local/share/cmd-find/commands/ssh/tunnel.sh ──
# Create an SSH tunnel forwarding local port 5432 to remote postgres
# Tags: ssh, postgres, tunnel
ssh -L 5432:localhost:5432 user@db-host.example.com
```

### Organising files

Directories are scanned recursively. Use subdirectories to group related commands:

```
~/.local/share/cmd-find/commands/
├── git/
│   ├── new-branch.sh
│   ├── squash-commits.sh
│   └── undo-commit.sh
├── docker/
│   ├── exec-shell.sh
│   └── prune.sh
├── ssh/
│   └── tunnel.sh
└── misc/
    └── find-large-files.sh
```

The directory structure does **not** affect searching — every command is pooled together and ranked purely by fuzzy match quality.

### Parameterised commands (arguments)

Commands can declare placeholders that you fill in interactively after selecting.
Use `# @param` lines to define arguments and `{{name}}` tokens in the command:

```bash
# SSH into a server with a custom port
# Tags: ssh, remote
# @param user | Username | text
# @param host | Hostname or IP | text
# @param port | SSH port | number | 22
ssh -p {{port}} {{user}}@{{host}}
```

When you select this command, an **argument form** appears:

```
  Fill arguments  SSH into a server with a custom port
──────────────────────────────────────────────────────────
> Username:  alice▌                          [text]
  Hostname:  (required)                      [text]
  Port:      22                              [#]
──────────────────────────────────────────────────────────
  Tab: next  |  Enter: confirm  |  Esc: cancel
```

Tab between fields, type values, Enter to confirm. The completed command is printed:

```
ssh -p 22 alice@db-host.example.com
```

#### Argument types

| Type | Syntax | Behaviour |
|---|---|---|
| `text` | `# @param name \| Label \| text` | Free text input |
| `number` | `# @param name \| Label \| number` | Numeric input |
| `path` | `# @param name \| Label \| path` | File/directory path |
| `flag` | `# @param name \| Label \| flag` | If filled (1/true/yes), inserts the flag name into the command. If empty or 0/false/no, the placeholder is removed entirely |
| `choice:a,b,c` | `# @param name \| Label \| choice:a,b,c` | Constrained to the listed options |

#### Defaults

The optional fourth `|` segment sets a default value — press Enter on a field to accept it:

```bash
# @param base | Base branch | text | main
# @param count | Number of commits | number | 3
```

#### Cross-reference defaults

A default can reference another argument:

```bash
# @param pr_number | Pull request number | number
# @param branch | Local branch name | text | pr-{{pr_number}}
git fetch origin pull/{{pr_number}}/head:{{branch}}
```

When `pr_number` is filled as `42`, the `branch` default automatically resolves to `pr-42`.

#### Static commands (no args)

Commands without `@param` lines work as before — selecting one prints the command immediately, no form appears:

```bash
# Undo the last commit, keeping all changes staged
# Tags: git, undo
git reset --soft HEAD~1
```

---

## Configuration

The config file lives at `~/.config/cmd-find/config.toml`:

```toml
# List directories containing .sh command templates.
# Paths support ~ and $ENV_VAR expansion.

directories = [
    "~/.local/share/cmd-find/commands",
    "~/work/team-scripts",
    "$PROJECT_DIR/oncall-runbooks",
]

# Default output mode when no flag is given.
#   "print" — output to stdout (for shell integration / Ctrl+F)
#   "copy"  — copy to system clipboard
#   "exec"  — execute immediately
mode = "print"
```

- Run `cmd-find --init` to create the default config.
- Directories that don't exist are silently skipped.
- Duplicate directories are deduplicated (order is preserved).
- Multiple config files: use `cmd-find -c /path/to/other-config.toml`.
- **Mode override:** `--exec`, `--copy`, and `--print` flags always take priority over the config `mode` setting.

---

## How it works

### Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  config.toml │────▶│   scanner    │────▶│   finder     │────▶│  arg form    │
│  directories │     │  parse .sh   │     │  fuzzy TUI   │     │  fill params │
└──────────────┘     └──────────────┘     └──────┬───────┘     └──────┬───────┘
                                                 │                    │
                    ┌────────────────────────────┘                    │
                    │  selected command (+ user values)               │
                    ▼                                                 │
          ┌─────────────────┐                                         │
          │  stdout / exec   │◀────────────────────────────────────────┘
          └─────────────────┘
```

**Config loader** (`config.py`) — reads the TOML file, expands `~` and `$ENV_VAR`, deduplicates paths. Falls back gracefully if no config exists.

**Scanner** (`scanner.py`) — walks every configured directory recursively for `.sh` files. Each file is parsed into a `Command` dataclass with a description (joined `#` lines), the command template (first executable line), optional tags (`# Tags: ...`), and optional argument definitions (`# @param ...`). Files with no command line are skipped. Also provides `fill_command()` which substitutes `{{placeholders}}` with user-provided values.

**Finder** (`finder.py`) — presents the interactive fuzzy-search UI. After selection, if the command has arguments, a second form appears for filling in values. Two backends:

| Backend | When | Features |
|---|---|---|
| **fzf** | `fzf` is on `$PATH` | Preview window, native fuzzy ranking, `--layout=reverse` |
| **Built-in** | no `fzf` found | Zero-dependency raw-terminal TUI with its own fuzzy scorer |

The built-in finder uses `termios`/`tty` for raw keyboard input, draws directly with ANSI escape codes, and scores matches with a simple algorithm that rewards consecutive-character matches and prefix matches.

### Fuzzy finder

1. On every keystroke the query is scored against each command's **description** (including tags).
2. Scoring is character-based: each matching char earns points; consecutive matches and prefix matches earn bonus points. Unmatched queries score `-1` and are hidden.
3. Results are sorted by score descending, then by original order.
4. The terminal is cleared and redrawn on every keystroke for instant feedback.

No external process is spawned in built-in mode. The UI runs entirely in `sys.stdin`/`sys.stdout`.

### Shell integration

The magic that pastes a command onto your command line:

```
┌─ shell widget (Ctrl+F) ─────────────────────────────────────────┐
│                                                                  │
│  1. User presses Ctrl+F                                         │
│  2. Shell invokes cmd-find with stderr→tty, stdout→pipe          │
│  3. cmd-find draws the TUI on /dev/tty                           │
│  4. User selects a command                                       │
│  5. cmd-find prints the raw command text to stdout               │
│  6. Shell captures stdout into $result                           │
│  7. READLINE_LINE / LBUFFER is set to $result + existing line    │
│  8. Cursor is positioned after the inserted command              │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

The key trick: the TUI renders to **stderr** (`2>/dev/tty`) so it appears on screen, while **stdout** is reserved for the result. This decouples the interactive display from the data channel the shell reads.

In Bash, `READLINE_LINE` and `READLINE_POINT` manipulate the readline buffer directly. In Zsh, `LBUFFER` and `zle reset-prompt` achieve the same effect. No temporary files, no `eval`, no `.bashrc` pollution.

---

## License

MIT
