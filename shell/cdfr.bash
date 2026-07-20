# ── cdfr shell integration for Bash ──────────────────────────────────────────
# Source this file in your ~/.bashrc to enable the Ctrl+G keybinding.
#
#   source /path/to/cmd-find/shell/cdfr.bash
#
# Press Ctrl+G to fuzzy-find a command and paste it onto your command line.

__cdfr_widget() {
    local result
    result=$(cdfr 2>/dev/tty)
    local ret=$?
    if [ $ret -eq 0 ] && [ -n "$result" ]; then
        READLINE_LINE="${result}${READLINE_LINE}"
        READLINE_POINT=${#result}
    fi
}

# Bind to Ctrl+G
bind -x '"\C-g": __cdfr_widget'
