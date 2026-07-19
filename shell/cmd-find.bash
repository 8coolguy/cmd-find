# ── cmd-find shell integration for Bash ─────────────────────────────────────
# Source this file in your ~/.bashrc to enable the Ctrl+F keybinding.
#
#   source /path/to/cmd-find/shell/cmd-find.bash
#
# Press Ctrl+F to fuzzy-find a command and paste it onto your command line.

__cmd_find_widget() {
    local result
    result=$(cmd-find 2>/dev/tty)
    local ret=$?
    if [ $ret -eq 0 ] && [ -n "$result" ]; then
        READLINE_LINE="${result}${READLINE_LINE}"
        READLINE_POINT=${#result}
    fi
}

# Bind to Ctrl+F
bind -x '"\C-f": __cmd_find_widget'
