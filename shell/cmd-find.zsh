# ── cmd-find shell integration for Zsh ──────────────────────────────────────
# Source this file in your ~/.zshrc to enable the Ctrl+F keybinding.
#
#   source /path/to/cmd-find/shell/cmd-find.zsh
#
# Press Ctrl+F to fuzzy-find a command and paste it onto your command line.

__cmd_find_widget() {
    local result
    result=$(cmd-find 2>/dev/tty)
    local ret=$?
    if [ $ret -eq 0 ] && [ -n "$result" ]; then
        LBUFFER="${LBUFFER}${result}"
    fi
    zle reset-prompt
}

zle -N __cmd_find_widget
bindkey '^F' __cmd_find_widget
