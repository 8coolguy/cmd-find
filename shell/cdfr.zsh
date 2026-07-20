# ── cdfr shell integration for Zsh ──────────────────────────────────────────
# Source this file in your ~/.zshrc to enable the Ctrl+G keybinding.
#
#   source /path/to/cmd-find/shell/cdfr.zsh
#
# Press Ctrl+G to fuzzy-find a command and paste it onto your command line.

__cdfr_widget() {
    local result
    result=$(cdfr 2>/dev/tty)
    local ret=$?
    if [ $ret -eq 0 ] && [ -n "$result" ]; then
        LBUFFER="${LBUFFER}${result}"
    fi
    zle reset-prompt
}

zle -N __cdfr_widget
bindkey '^G' __cdfr_widget
