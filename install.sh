#!/usr/bin/env bash
# ── cdfr installer ──────────────────────────────────────────────────────────
# Usage: ./install.sh
#
# This script:
#  1. Installs the cdfr CLI globally via uv (or pip as fallback)
#  2. Creates a default config at ~/.config/cdfr/config.toml
#  3. Copies example commands to ~/.local/share/cdfr/commands/
#  4. Prints shell integration instructions

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${HOME}/.local/share/cdfr"
COMMANDS_DIR="${INSTALL_DIR}/commands"

echo "╔══════════════════════════════════════════╗"
echo "║        cdfr      —  installer           ║"
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
if ! command -v cdfr &>/dev/null; then
    # Try to locate it
    if [[ -x "${HOME}/.local/bin/cdfr" ]]; then
        export PATH="${HOME}/.local/bin:${PATH}"
    elif [[ -x "${HOME}/.cargo/bin/cdfr" ]]; then
        export PATH="${HOME}/.cargo/bin:${PATH}"
    fi
fi

# ── 3. Create default config ────────────────────────────────────────────────

echo "→ Creating default config..."
cdfr --init 2>/dev/null || python3 -m cmd_find.main --init 2>/dev/null || true

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
echo "    source ${SCRIPT_DIR}/shell/cdfr.bash"
echo ""
echo "  Zsh  — add to ~/.zshrc:"
echo "    source ${SCRIPT_DIR}/shell/cdfr.zsh"
echo ""
echo "  Then press Ctrl+G to fuzzy-find commands!"
echo ""
echo "  Or run directly:"
echo "    cdfr        # select and print command"
echo "    cdfr --exec # select and execute"
echo "    cdfr --list # list all commands"
echo ""
echo "  Config: ~/.config/cdfr/config.toml"
echo "  Commands dir: $COMMANDS_DIR"
