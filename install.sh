#!/usr/bin/env bash
# ── cmd-find installer ──────────────────────────────────────────────────────
# Usage: ./install.sh
#
# This script:
#  1. Installs the cmd-find CLI globally via uv (or pip as fallback)
#  2. Creates a default config at ~/.config/cmd-find/config.toml
#  3. Copies example commands to ~/.local/share/cmd-find/commands/
#  4. Prints shell integration instructions

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${HOME}/.local/share/cmd-find"
COMMANDS_DIR="${INSTALL_DIR}/commands"

echo "╔══════════════════════════════════════════╗"
echo "║        cmd-find  —  installer           ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. Install Python package ──────────────────────────────────────────────

cd "$SCRIPT_DIR"

if command -v uv &>/dev/null; then
    echo "→ Installing with uv (editable, isolated venv)..."
    uv tool install --editable . 2>&1
elif command -v pip &>/dev/null; then
    echo "→ uv not found; falling back to pip..."
    pip install --user --break-system-packages -e . 2>&1 | tail -3
else
    echo "✗ Neither uv nor pip found. Install one and retry."
    exit 1
fi

# ── 2. Ensure the command is on PATH ────────────────────────────────────────

# uv tool install puts binaries in ~/.local/bin
if ! command -v cmd-find &>/dev/null; then
    # Try to locate it
    if [[ -x "${HOME}/.local/bin/cmd-find" ]]; then
        export PATH="${HOME}/.local/bin:${PATH}"
    elif [[ -x "${HOME}/.cargo/bin/cmd-find" ]]; then
        export PATH="${HOME}/.cargo/bin:${PATH}"
    fi
fi

# ── 3. Create default config ────────────────────────────────────────────────

echo "→ Creating default config..."
cmd-find --init 2>/dev/null || python3 -m cmd_find.main --init 2>/dev/null || true

# ── 4. Copy example commands ────────────────────────────────────────────────

if [ -d "$SCRIPT_DIR/example-commands" ]; then
    echo "→ Copying example commands to $COMMANDS_DIR ..."
    mkdir -p "$COMMANDS_DIR"
    cp -r "$SCRIPT_DIR/example-commands/"* "$COMMANDS_DIR/"
    echo "  Done."
fi

# ── Done ────────────────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Installation complete!                 ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  Shell integration (pick one):"
echo ""
echo "  Bash — add to ~/.bashrc:"
echo "    source ${SCRIPT_DIR}/shell/cmd-find.bash"
echo ""
echo "  Zsh  — add to ~/.zshrc:"
echo "    source ${SCRIPT_DIR}/shell/cmd-find.zsh"
echo ""
echo "  Then press Ctrl+F to fuzzy-find commands!"
echo ""
echo "  Or run directly:"
echo "    cmd-find        # select and print command"
echo "    cmd-find --exec # select and execute"
echo "    cmd-find --list # list all commands"
echo ""
echo "  Config: ~/.config/cmd-find/config.toml"
echo "  Commands dir: $COMMANDS_DIR"
