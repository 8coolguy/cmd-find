"""Interactive fuzzy finder — built-in fallback + optional fzf integration."""

import os
import shutil
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path
from typing import List, Optional

from .scanner import Command


# ── fzf backend ──────────────────────────────────────────────────────────────

def _has_fzf() -> bool:
    return shutil.which("fzf") is not None


def _run_fzf(commands: List[Command]) -> Command | None:
    """Pipe commands into fzf and return the selected one."""
    lines = []
    for cmd in commands:
        # Description on the left, command dimmed on the right
        tag_str = f"[{','.join(cmd.tags)}] " if cmd.tags else ""
        lines.append(f"{tag_str}{cmd.description} │ {cmd.command}")

    input_text = "\n".join(lines)

    proc = subprocess.run(
        [
            "fzf",
            "--delimiter=│",
            "--with-nth=1",
            "--preview",
            "echo {2}",
            "--preview-window=bottom:1:wrap",
            "--height=40%",
            "--layout=reverse",
            "--border",
            "--prompt=cmd> ",
        ],
        input=input_text,
        capture_output=True,
        text=True,
    )

    if proc.returncode != 0:
        return None

    selected = proc.stdout.strip()
    if not selected:
        return None

    # Extract the index by finding the original command
    for cmd in commands:
        tag_str = f"[{','.join(cmd.tags)}] " if cmd.tags else ""
        line = f"{tag_str}{cmd.description} │ {cmd.command}"
        if line == selected:
            return cmd

    return None


# ── Built-in fuzzy finder ────────────────────────────────────────────────────

def _fuzzy_match(query: str, text: str) -> float:
    """Score how well `query` fuzzy-matches `text`.

    Returns a score (higher is better) or -1 for no match.
    Consecutive character matches get a bonus.
    """
    query = query.lower()
    text = text.lower()

    if not query:
        return 0.0

    score = 0.0
    qi = 0
    prev_match = -2

    for ti, tc in enumerate(text):
        if qi >= len(query):
            break
        if tc == query[qi]:
            # Bonus for consecutive matches and prefix matches
            if ti == prev_match + 1:
                score += 2.0
            elif ti == 0:
                score += 1.5
            else:
                score += 1.0
            prev_match = ti
            qi += 1

    if qi < len(query):
        return -1.0  # not all chars matched

    # Penalize longer distances (normalized)
    return score


def _visible_len(text: str) -> int:
    """Return the visible length of a string, ignoring ANSI escape codes."""
    import re
    return len(re.sub(r"\x1b\[[0-9;]*m", "", text))


def _truncate(text: str, max_width: int) -> str:
    """Truncate text to max_width visible characters, appending '…' if cut."""
    if _visible_len(text) <= max_width:
        return text
    # Walk through, skipping ANSI codes, counting visible characters
    result: List[str] = []
    visible = 0
    i = 0
    while i < len(text) and visible < max_width - 1:
        if text[i] == "\x1b":
            # Skip the entire escape sequence
            end = text.index("m", i) + 1
            result.append(text[i:end])
            i = end
        else:
            result.append(text[i])
            visible += 1
            i += 1
    return "".join(result) + "…"


def _pad_to(text: str, width: int) -> str:
    """Right-pad text with spaces to reach visible width."""
    vlen = _visible_len(text)
    if vlen >= width:
        return text
    return text + " " * (width - vlen)


def _render_screen(
    commands: List[Command],
    query: str,
    selected_idx: int,
    term_width: int,
    term_height: int,
) -> str:
    """Render the TUI screen with the query bar pinned to the bottom.

    Layout:
      ┌─ header: title + match count (fixed, top)
      ├─ divider
      ├─ item list (scrollable, fills remaining space)
      ├─ divider
      ├─ preview: full command of selected item (fixed)
      ├─ divider
      ├─ query input line (fixed, bottom — always visible)
      └─ keybinding hints (fixed, bottom)
    """
    # Score and filter — search against description + tags
    scored: List[tuple[float, int, Command]] = []
    for i, cmd in enumerate(commands):
        search_text = cmd.description
        if cmd.tags:
            search_text += " " + " ".join(cmd.tags)
        s = _fuzzy_match(query, search_text)
        if s >= 0 or not query:
            scored.append((s, i, cmd))

    # Sort by score descending
    scored.sort(key=lambda x: (-x[0], x[1]))

    total_matches = len(scored)

    # Fixed non-list lines: header(1) + divider(1) + preview(1) + divider(1)
    #                       + query(1) + divider(1) + footer(1) = 7 lines
    list_height = max(1, term_height - 7)
    display = scored[:list_height]

    # Clamp selected index
    if selected_idx < 0:
        selected_idx = 0
    if selected_idx >= len(display):
        selected_idx = max(0, len(display) - 1)

    w = term_width
    lines: List[str] = []

    # ── Header ──────────────────────────────────────────────────────────
    header = "  \x1b[1;36mcmd-find\x1b[0m"
    counter = f"\x1b[90m({selected_idx + 1}/{total_matches})\x1b[0m" if total_matches else ""
    available = w - _visible_len(header) - _visible_len(counter) - 1
    if available < 1:
        lines.append(_truncate(header, w))
    else:
        lines.append(f"{header}{' ' * available}{counter}")

    lines.append("\x1b[90m" + "─" * w + "\x1b[0m")

    # ── Item list ───────────────────────────────────────────────────────
    if not display:
        lines.append("\x1b[90m  No matches\x1b[0m")
        lines.extend([""] * (list_height - 1))
    else:
        for di, (score, _, cmd) in enumerate(display):
            if di == selected_idx:
                prefix = "\x1b[1;32m>\x1b[0m "
            else:
                prefix = "  "

            if cmd.tags:
                tag = f"\x1b[35m[{','.join(cmd.tags)}]\x1b[0m "
            else:
                tag = ""

            desc = cmd.description
            if query:
                desc = _highlight_match(desc, query)

            line = f"{prefix}{tag}{desc}"
            line = _truncate(line, w)
            lines.append(line)

        for _ in range(list_height - len(display)):
            lines.append("")

    # ── Preview ─────────────────────────────────────────────────────────
    lines.append("\x1b[90m" + "─" * w + "\x1b[0m")
    if display and selected_idx < len(display):
        preview_cmd = display[selected_idx][2].command
        preview = f"  \x1b[90m{preview_cmd}\x1b[0m"
        lines.append(_truncate(preview, w))
    else:
        lines.append("")

    # ── Query (bottom) ──────────────────────────────────────────────────
    lines.append("\x1b[90m" + "─" * w + "\x1b[0m")
    q = query if query else ""
    lines.append(f"  \x1b[1;33m> {q}\x1b[0m" + "\x1b[5m \x1b[0m")

    # ── Footer ──────────────────────────────────────────────────────────
    footer = "  \x1b[90m↑↓ nav  │  type filter  │  Enter select  │  Ctrl+D del  │  Ctrl+N new  │  Ctrl+H hist\x1b[0m"
    lines.append(_truncate(footer, w))

    return "\r\n".join(lines), selected_idx


def _highlight_match(text: str, query: str) -> str:
    """Highlight fuzzy-matched characters in text."""
    result: List[str] = []
    qi = 0
    query_lower = query.lower()
    for ch in text:
        if qi < len(query_lower) and ch.lower() == query_lower[qi]:
            result.append(f"\x1b[1;33m{ch}\x1b[0m")
            qi += 1
        else:
            result.append(ch)
    return "".join(result)


def _confirm_delete(
    target: Command,
    term_width: int,
    term_height: int,
) -> bool:
    """Show a confirmation prompt and return True if the user confirms deletion."""
    fd = sys.stdin.fileno()

    msg = f"  \x1b[1;31mDelete\x1b[0m  \x1b[90m{target.description[:60]}\x1b[0m"
    file_info = f"  \x1b[90msource: {target.source_file}\x1b[0m"
    prompt = "  \x1b[1;33mDelete this command? (y/N)\x1b[0m"

    # Render the confirmation overlay once
    sys.stdout.write("\x1b[H\x1b[J")
    lines = [
        "",
        "",
        "",
        "\x1b[90m" + "─" * term_width + "\x1b[0m",
        msg,
        file_info,
        "",
        prompt,
        "\x1b[90m" + "─" * term_width + "\x1b[0m",
    ]
    sys.stdout.write("\r\n".join(lines))
    sys.stdout.flush()

    # Wait for y/n
    while True:
        ch = sys.stdin.read(1)
        if ch.lower() == "y":
            return True
        elif ch.lower() == "n" or ch == "\x1b" or ch == "\x03" or ch in ("\r", "\n"):
            return False


def _builtin_find(commands: List[Command], save_dir: Path) -> Command | None:
    """Run the built-in interactive fuzzy finder."""
    if not commands:
        print("No commands found in configured directories.", file=sys.stderr)
        return None

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        tty.setraw(fd)
        query = ""
        selected_idx = 0
        term_size = shutil.get_terminal_size()

        while True:
            term_size = shutil.get_terminal_size()
            term_width = term_size.columns
            term_height = term_size.lines

            # Move cursor to top-left and render
            sys.stdout.write("\x1b[H\x1b[J")
            screen, selected_idx = _render_screen(
                commands, query, selected_idx, term_width, term_height
            )
            sys.stdout.write(screen)
            sys.stdout.flush()

            # Read a key
            ch = sys.stdin.read(1)

            if ch == "\x1b":
                # Escape sequence (arrow keys, Esc)
                seq = sys.stdin.read(2)
                if seq == "[A":  # Up
                    selected_idx = max(0, selected_idx - 1)
                elif seq == "[B":  # Down
                    selected_idx += 1
                elif seq == "[C":  # Right (ignore)
                    pass
                elif seq == "[D":  # Left (ignore)
                    pass
                elif seq == "[3" or seq == "[P":  # Delete key (just ignore)
                    pass
                else:
                    # Esc pressed
                    return None
            elif ch == "\x03":  # Ctrl-C
                return None
            elif ch == "\x04":  # Ctrl-D — delete selected command
                # Resolve which command is actually selected
                scored = []
                for i, cmd in enumerate(commands):
                    search_text = cmd.description
                    if cmd.tags:
                        search_text += " " + " ".join(cmd.tags)
                    s = _fuzzy_match(query, search_text)
                    if s >= 0 or not query:
                        scored.append((s, i, cmd))
                scored.sort(key=lambda x: (-x[0], x[1]))
                list_height = max(1, term_height - 7)
                display = scored[:list_height]
                sidx = selected_idx
                if sidx < 0:
                    sidx = 0
                if sidx >= len(display):
                    sidx = max(0, len(display) - 1)

                if not display:
                    continue

                target = display[sidx][2]
                confirmed = _confirm_delete(target, term_width, term_height)
                if confirmed:
                    try:
                        target.source_file.unlink()
                    except OSError:
                        pass  # file already gone or permission denied
                    commands = [c for c in commands if c.source_file != target.source_file]
                    selected_idx = max(0, sidx - 1)
                    query = ""  # reset so all remaining commands show
            elif ch == "\x0e":  # Ctrl+N — new command
                new_cmd = _prompt_new_command(save_dir)
                if new_cmd is not None:
                    commands.append(new_cmd)
                    commands.sort(key=lambda c: str(c.source_file))
                    selected_idx = 0
                    query = ""
            elif ch == "\x08":  # Ctrl+H — search history
                new_cmd = _history_mode(save_dir)
                if new_cmd is not None:
                    commands.append(new_cmd)
                    commands.sort(key=lambda c: str(c.source_file))
                    selected_idx = 0
                    query = ""
            elif ch in ("\r", "\n"):  # Enter
                # Return the selected command
                scored = []
                for i, cmd in enumerate(commands):
                    search_text = cmd.description
                    if cmd.tags:
                        search_text += " " + " ".join(cmd.tags)
                    s = _fuzzy_match(query, search_text)
                    if s >= 0 or not query:
                        scored.append((s, i, cmd))
                scored.sort(key=lambda x: (-x[0], x[1]))
                list_height = max(1, term_height - 7)
                display = scored[:list_height]
                if selected_idx < 0:
                    selected_idx = 0
                if selected_idx >= len(display):
                    selected_idx = max(0, len(display) - 1)
                if display:
                    return display[selected_idx][2]
                return None
            elif ch == "\x7f":  # Backspace
                query = query[:-1]
                selected_idx = 0
            elif ch.isprintable():
                query += ch
                selected_idx = 0
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        # Clear screen and reset cursor
        sys.stdout.write("\x1b[H\x1b[J")
        sys.stdout.flush()

    return None


# ── Shell history loader ────────────────────────────────────────────────────

def _load_shell_history() -> List[str]:
    """Read commands from bash/zsh history files, deduplicated (most recent kept)."""
    home = Path.home()
    candidates = [
        home / ".bash_history",
        home / ".zsh_history",
        home / ".local/share/fish/fish_history",
    ]

    commands: List[str] = []
    seen: set[str] = set()

    for hist_file in candidates:
        if not hist_file.is_file():
            continue
        try:
            with open(hist_file, errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    # Zsh extended history: ': 1234567890:0;command'
                    if line.startswith(":"):
                        parts = line.split(";", 1)
                        if len(parts) == 2:
                            line = parts[1].strip()
                        else:
                            continue

                    if line and line not in seen:
                        seen.add(line)
                        commands.append(line)
        except (OSError, UnicodeDecodeError):
            continue

    # Most recent first (files are in chronological order, reverse for recency)
    commands.reverse()
    return commands


# ── Slugify for filenames ───────────────────────────────────────────────────

def _slugify(text: str, max_len: int = 40) -> str:
    """Turn a description into a safe filename slug."""
    import re
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "-", slug)
    return slug[:max_len].strip("-")


# ── New command form (Ctrl+N) ────────────────────────────────────────────────

def _render_new_cmd_form(
    description: str,
    tags: str,
    command: str,
    active_idx: int,
    term_width: int,
) -> str:
    """Render the 'new command' creation form."""
    w = term_width
    lines: List[str] = []

    lines.append("  \x1b[1;36mNew command\x1b[0m")
    lines.append("\x1b[90m" + "─" * w + "\x1b[0m")

    fields = [
        ("Description", description),
        ("Tags", tags),
        ("Command", command),
    ]

    for i, (label, value) in enumerate(fields):
        if i == active_idx:
            marker = "\x1b[1;32m>\x1b[0m"
            label_str = f"\x1b[1;37m{label}:\x1b[0m"
            cursor = "\x1b[5m \x1b[0m"
            val_str = f"\x1b[1;33m{value}{cursor}\x1b[0m" if value else cursor
        else:
            marker = " "
            label_str = f"\x1b[90m{label}:\x1b[0m"
            val_str = f"\x1b[1;33m{value}\x1b[0m" if value else "\x1b[90m(empty)\x1b[0m"

        line = f" {marker} {label_str} {val_str}"
        lines.append(_truncate(line, w))

    for _ in range(4):
        lines.append("")

    lines.append("\x1b[90m" + "─" * w + "\x1b[0m")
    footer = "  \x1b[90mTab: next  │  Enter: save  │  Esc: cancel\x1b[0m"
    lines.append(_truncate(footer, w))

    return "\r\n".join(lines)


def _prompt_new_command(save_dir: Path) -> Command | None:
    """Interactive form to create a new command and save it as a .sh file."""

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    description = ""
    tags = ""
    command = ""
    active_idx = 0

    try:
        tty.setraw(fd)

        while True:
            term_size = shutil.get_terminal_size()
            term_width = term_size.columns

            sys.stdout.write("\x1b[H\x1b[J")
            sys.stdout.write(
                _render_new_cmd_form(description, tags, command, active_idx, term_width)
            )
            sys.stdout.flush()

            ch = sys.stdin.read(1)

            if ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[A":  # Up
                    active_idx = max(0, active_idx - 1)
                elif seq == "[B":  # Down
                    active_idx = min(2, active_idx + 1)
                else:
                    return None  # Esc
            elif ch == "\x03":  # Ctrl-C
                return None
            elif ch == "\t":  # Tab
                active_idx = (active_idx + 1) % 3
            elif ch in ("\r", "\n"):  # Enter — save
                if not command.strip():
                    continue  # command is required
                break
            elif ch == "\x7f":  # Backspace
                if active_idx == 0:
                    description = description[:-1]
                elif active_idx == 1:
                    tags = tags[:-1]
                else:
                    command = command[:-1]
            elif ch.isprintable():
                if active_idx == 0:
                    description += ch
                elif active_idx == 1:
                    tags += ch
                else:
                    command += ch

        # Save as .sh file
        save_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(description) if description.strip() else "cmd"
        ts = int(time.time())
        filepath = save_dir / f"{slug}-{ts}.sh"

        # Build file content
        lines: List[str] = []
        if description.strip():
            lines.append(f"# {description.strip()}")
        if tags.strip():
            lines.append(f"# Tags: {tags.strip()}")
        lines.append(command.strip())

        filepath.write_text("\n".join(lines) + "\n")

        return Command(
            description=description.strip() or _slugify(command.strip()),
            command=command.strip(),
            source_file=filepath,
            tags=[t.strip() for t in tags.split(",") if t.strip()],
        )

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write("\x1b[H\x1b[J")
        sys.stdout.flush()

    return None


# ── History mode (Ctrl+H) ───────────────────────────────────────────────────

def _render_history_form(
    cmd_text: str,
    description: str,
    tags: str,
    active_idx: int,
    term_width: int,
) -> str:
    """Render the form shown after selecting a history command."""
    w = term_width
    lines: List[str] = []

    lines.append("  \x1b[1;36mSave from history\x1b[0m")
    lines.append("\x1b[90m" + "─" * w + "\x1b[0m")
    lines.append(f"  \x1b[90mCommand: {_truncate(cmd_text, w - 11)}\x1b[0m")
    lines.append("")

    fields = [
        ("Description", description),
        ("Tags", tags),
    ]

    for i, (label, value) in enumerate(fields):
        if i == active_idx:
            marker = "\x1b[1;32m>\x1b[0m"
            label_str = f"\x1b[1;37m{label}:\x1b[0m"
            cursor = "\x1b[5m \x1b[0m"
            val_str = f"\x1b[1;33m{value}{cursor}\x1b[0m" if value else cursor
        else:
            marker = " "
            label_str = f"\x1b[90m{label}:\x1b[0m"
            val_str = f"\x1b[1;33m{value}\x1b[0m" if value else "\x1b[90m(empty)\x1b[0m"

        line = f" {marker} {label_str} {val_str}"
        lines.append(_truncate(line, w))

    for _ in range(4):
        lines.append("")

    lines.append("\x1b[90m" + "─" * w + "\x1b[0m")
    footer = "  \x1b[90mTab: next  │  Enter: save  │  Esc: cancel\x1b[0m"
    lines.append(_truncate(footer, w))

    return "\r\n".join(lines)


def _history_mode(save_dir: Path) -> Command | None:
    """Browse shell history, select a command, add description/tags, and save."""

    history_cmds = _load_shell_history()
    if not history_cmds:
        # Show message briefly
        sys.stdout.write("\x1b[H\x1b[J")
        sys.stdout.write("\r\n  No shell history found.\r\n")
        sys.stdout.write("  (Checked ~/.bash_history and ~/.zsh_history)\r\n")
        sys.stdout.flush()
        # Wait for any key
        sys.stdin.read(1)
        return None

    # Build virtual Command objects for the finder
    history_commands: List[Command] = []
    for cmd_text in history_cmds:
        history_commands.append(Command(
            description=cmd_text[:80],
            command=cmd_text,
            source_file=Path("<history>"),
        ))

    # Use the built-in finder to let user search through history
    # Temporarily — we need a finder that shows these and returns one.
    # We can reuse _builtin_find but we need a different render header.
    # Simpler: just run _builtin_find with the history commands, but
    # we need to intercept the result to add description/tags form.

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    selected_cmd: str | None = None

    try:
        tty.setraw(fd)
        query = ""
        selected_idx = 0

        while True:
            term_size = shutil.get_terminal_size()
            term_width = term_size.columns
            term_height = term_size.lines

            # Score and filter
            scored: List[tuple[float, int, Command]] = []
            for i, cmd in enumerate(history_commands):
                s = _fuzzy_match(query, cmd.description)
                if s >= 0 or not query:
                    scored.append((s, i, cmd))
            scored.sort(key=lambda x: (-x[0], x[1]))
            total_matches = len(scored)
            list_height = max(1, term_height - 7)
            display = scored[:list_height]

            if selected_idx < 0:
                selected_idx = 0
            if selected_idx >= len(display):
                selected_idx = max(0, len(display) - 1)

            # Render with history-specific header
            w = term_width
            lines: List[str] = []
            header = "  \x1b[1;36mHistory\x1b[0m"
            counter = f"\x1b[90m({selected_idx + 1}/{total_matches})\x1b[0m" if total_matches else ""
            available = w - _visible_len(header) - _visible_len(counter) - 1
            if available < 1:
                lines.append(_truncate(header, w))
            else:
                lines.append(f"{header}{' ' * available}{counter}")
            lines.append("\x1b[90m" + "─" * w + "\x1b[0m")

            if not display:
                lines.append("\x1b[90m  No matches\x1b[0m")
                lines.extend([""] * (list_height - 1))
            else:
                for di, (score, _, cmd) in enumerate(display):
                    if di == selected_idx:
                        prefix = "\x1b[1;32m>\x1b[0m "
                    else:
                        prefix = "  "
                    desc = cmd.description
                    if query:
                        desc = _highlight_match(desc, query)
                    line = _truncate(f"{prefix}{desc}", w)
                    lines.append(line)
                for _ in range(list_height - len(display)):
                    lines.append("")

            lines.append("\x1b[90m" + "─" * w + "\x1b[0m")
            if display and selected_idx < len(display):
                preview_cmd = display[selected_idx][2].command
                preview = f"  \x1b[90m{preview_cmd}\x1b[0m"
                lines.append(_truncate(preview, w))
            else:
                lines.append("")

            lines.append("\x1b[90m" + "─" * w + "\x1b[0m")
            footer = "  \x1b[90m↑↓ nav  │  type filter  │  Enter pick  │  Esc back\x1b[0m"
            lines.append(_truncate(footer, w))

            sys.stdout.write("\x1b[H\x1b[J")
            sys.stdout.write("\r\n".join(lines))
            sys.stdout.flush()

            ch = sys.stdin.read(1)

            if ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[A":
                    selected_idx = max(0, selected_idx - 1)
                elif seq == "[B":
                    selected_idx += 1
                else:
                    return None  # Esc goes back
            elif ch == "\x03":
                return None
            elif ch in ("\r", "\n"):
                if not display:
                    continue
                sidx = selected_idx
                if sidx < 0:
                    sidx = 0
                if sidx >= len(display):
                    sidx = max(0, len(display) - 1)
                selected_cmd = display[sidx][2].command
                break
            elif ch == "\x7f":
                query = query[:-1]
                selected_idx = 0
            elif ch.isprintable():
                query += ch
                selected_idx = 0

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    if selected_cmd is None:
        sys.stdout.write("\x1b[H\x1b[J")
        sys.stdout.flush()
        return None

    # Now prompt for description and tags
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    description = ""
    tags = ""
    active_idx = 0

    try:
        tty.setraw(fd)

        while True:
            term_size = shutil.get_terminal_size()
            term_width = term_size.columns

            sys.stdout.write("\x1b[H\x1b[J")
            sys.stdout.write(
                _render_history_form(selected_cmd, description, tags, active_idx, term_width)
            )
            sys.stdout.flush()

            ch = sys.stdin.read(1)

            if ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[A":
                    active_idx = max(0, active_idx - 1)
                elif seq == "[B":
                    active_idx = min(1, active_idx + 1)
                else:
                    return None
            elif ch == "\x03":
                return None
            elif ch == "\t":
                active_idx = (active_idx + 1) % 2
            elif ch in ("\r", "\n"):
                break
            elif ch == "\x7f":
                if active_idx == 0:
                    description = description[:-1]
                else:
                    tags = tags[:-1]
            elif ch.isprintable():
                if active_idx == 0:
                    description += ch
                else:
                    tags += ch

        # Save as .sh file
        save_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(description) if description.strip() else "cmd"
        ts = int(time.time())
        filepath = save_dir / f"{slug}-{ts}.sh"

        file_lines: List[str] = []
        if description.strip():
            file_lines.append(f"# {description.strip()}")
        if tags.strip():
            file_lines.append(f"# Tags: {tags.strip()}")
        file_lines.append(selected_cmd.strip())

        filepath.write_text("\n".join(file_lines) + "\n")

        return Command(
            description=description.strip() or _slugify(selected_cmd.strip()),
            command=selected_cmd.strip(),
            source_file=filepath,
            tags=[t.strip() for t in tags.split(",") if t.strip()],
        )

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write("\x1b[H\x1b[J")
        sys.stdout.flush()

    return None


# ── Argument input form ─────────────────────────────────────────────────────

def _render_arg_form(
    cmd: Command,
    values: dict[str, str],
    active_idx: int,
    term_width: int,
    term_height: int,
) -> str:
    """Render the argument-filling form."""
    w = term_width
    lines: List[str] = []

    # Header
    header = f"  \x1b[1;36mFill arguments\x1b[0m  \x1b[90m{cmd.description}\x1b[0m"
    lines.append(_truncate(header, w))
    lines.append("\x1b[90m" + "─" * w + "\x1b[0m")

    if not cmd.args:
        lines.append("  \x1b[90mNo arguments needed. Press Enter to confirm.\x1b[0m")
    else:
        for i, arg in enumerate(cmd.args):
            val = values.get(arg.name, arg.default)

            # Active field indicator
            if i == active_idx:
                marker = "\x1b[1;32m>\x1b[0m"
                label = f"\x1b[1;37m{arg.description}:\x1b[0m"
            else:
                marker = " "
                label = f"\x1b[90m{arg.description}:\x1b[0m"

            # Type hint
            type_hint = _arg_type_label(arg)

            # Value display
            if i == active_idx:
                # Show value with cursor
                cursor = "\x1b[5m \x1b[0m" if val else "\x1b[5m_\x1b[0m"
                if val:
                    value_str = f"\x1b[1;33m{val}{cursor}\x1b[0m"
                else:
                    value_str = cursor
            else:
                if val:
                    value_str = f"\x1b[1;33m{val}\x1b[0m"
                elif arg.default:
                    value_str = f"\x1b[90m({arg.default})\x1b[0m"
                else:
                    value_str = "\x1b[90m(required)\x1b[0m"

            line = f" {marker} {label} {value_str}  {type_hint}"
            lines.append(_truncate(line, w))

    # Pad to keep layout stable
    visible_fields = len(cmd.args) if cmd.args else 1
    pad_needed = max(0, 8 - visible_fields)
    for _ in range(pad_needed):
        lines.append("")

    # Footer
    lines.append("\x1b[90m" + "─" * w + "\x1b[0m")
    footer = "  \x1b[90mTab: next  │  Enter: confirm  │  Esc: cancel\x1b[0m"
    lines.append(_truncate(footer, w))

    return "\r\n".join(lines)


def _arg_type_label(arg) -> str:
    """Return a short type badge for an argument."""
    t = arg.type.lower()
    if t == "text":
        return "\x1b[90m[text]\x1b[0m"
    elif t == "number":
        return "\x1b[90m[#]\x1b[0m"
    elif t == "path":
        return "\x1b[90m[path]\x1b[0m"
    elif t == "flag":
        return "\x1b[90m[flag]\x1b[0m"
    elif t.startswith("choice:"):
        opts = t[7:]
        return f"\x1b[90m[{opts}]\x1b[0m"
    return ""


def _fill_args(cmd: Command) -> dict[str, str] | None:
    """Interactive argument-filling form.

    Returns a dict of arg_name → value, or None if the user cancelled.
    """
    if not cmd.has_args:
        return {}

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    values: dict[str, str] = {}
    active_idx = 0

    try:
        tty.setraw(fd)

        while True:
            term_size = shutil.get_terminal_size()
            term_width = term_size.columns
            term_height = term_size.lines

            sys.stdout.write("\x1b[H\x1b[J")
            sys.stdout.write(
                _render_arg_form(cmd, values, active_idx, term_width, term_height)
            )
            sys.stdout.flush()

            ch = sys.stdin.read(1)

            if ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[A":  # Up
                    active_idx = max(0, active_idx - 1)
                elif seq == "[B":  # Down
                    active_idx = min(len(cmd.args) - 1, active_idx + 1)
                elif seq == "[Z":  # Shift+Tab
                    active_idx = max(0, active_idx - 1)
                else:
                    return None  # Esc
            elif ch == "\x03":  # Ctrl-C
                return None
            elif ch == "\t":  # Tab
                active_idx = (active_idx + 1) % len(cmd.args)
            elif ch in ("\r", "\n"):  # Enter — confirm
                # Apply defaults for unfilled fields
                for arg in cmd.args:
                    if arg.name not in values and arg.default:
                        values[arg.name] = arg.default
                return values
            elif ch == "\x7f":  # Backspace
                cur_name = cmd.args[active_idx].name
                values[cur_name] = values.get(cur_name, "")[:-1]
            elif ch.isprintable():
                cur_name = cmd.args[active_idx].name
                values[cur_name] = values.get(cur_name, "") + ch

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write("\x1b[H\x1b[J")
        sys.stdout.flush()

    return None


# ── Public API ───────────────────────────────────────────────────────────────

def run_finder(commands: List[Command], save_dir: Path) -> Command | None:
    """Run the fuzzy finder and return the selected Command (or None).

    Uses fzf if available, otherwise falls back to the built-in finder.
    """
    if not commands:
        sys.stdout.write("\x1b[H\x1b[J")
        print("cmd-find: No commands found in configured directories.", file=sys.stderr)
        print(
            "Add .sh files to your command directories and try again.",
            file=sys.stderr,
        )
        return None

    if _has_fzf():
        return _run_fzf(commands)
    else:
        return _builtin_find(commands, save_dir)


# ── Flashcard mode ──────────────────────────────────────────────────────────

def _render_flashcard(
    cmd: Command,
    card_index: int,
    total: int,
    correct: int,
    wrong: int,
    revealed: bool,
    term_width: int,
    term_height: int,
) -> str:
    """Render one flashcard."""
    w = term_width
    lines: List[str] = []

    # Header with progress and score
    progress = f"  \x1b[1;36mFlashcard\x1b[0m  {card_index}/{total}"
    score = f"\x1b[32m✓ {correct}\x1b[0m  \x1b[31m✗ {wrong}\x1b[0m"
    available = w - _visible_len(progress) - _visible_len(score) - 2
    if available < 1:
        lines.append(_truncate(progress + "  " + score, w))
    else:
        lines.append(f"{progress}{' ' * available}{score}")

    lines.append("\x1b[90m" + "─" * w + "\x1b[0m")

    # Tags
    if cmd.tags:
        tags_line = f"  \x1b[35m[{','.join(cmd.tags)}]\x1b[0m"
        lines.append(_truncate(tags_line, w))

    # Description (word-wrapped simply by truncating long lines)
    desc = cmd.description
    while desc:
        lines.append(_truncate(f"  {desc}", w))
        break  # Keep it simple: one line, truncated

    # Spacer
    for _ in range(max(1, term_height - len(lines) - 4)):
        lines.append("")

    # Revealed command
    if revealed:
        lines.append("\x1b[90m" + "─" * w + "\x1b[0m")
        cmd_line = f"  \x1b[1;33m{cmd.command}\x1b[0m"
        lines.append(_truncate(cmd_line, w))
        lines.append("")
        lines.append("\x1b[90m" + "─" * w + "\x1b[0m")
        footer = "  \x1b[90my: got it  │  n: need practice  │  Esc: quit\x1b[0m"
    else:
        lines.append("\x1b[90m" + "─" * w + "\x1b[0m")
        lines.append("  \x1b[90mPress Enter or Space to reveal\x1b[0m")
        lines.append("")
        footer = "  \x1b[90mEsc: quit\x1b[0m"

    lines.append(_truncate(footer, w))

    return "\r\n".join(lines)


def flashcard_mode(commands: List[Command]) -> None:
    """Interactive flashcard mode — practice memorising commands.

    Cards are shuffled. Each card shows description + tags on the front.
    Press Enter to reveal the command, then y (got it) or n (need practice).
    Cards marked 'n' go back to the end of the queue.
    """
    import random

    if not commands:
        sys.stdout.write("\x1b[H\x1b[J")
        print("No commands to practice.", file=sys.stderr)
        return

    if not sys.stdin.isatty():
        print("Flashcard mode requires an interactive terminal.", file=sys.stderr)
        return

    # Shuffle a copy
    queue: List[Command] = list(commands)
    random.shuffle(queue)

    original_count = len(queue)
    correct = 0
    wrong = 0
    revealed = False
    current_idx = 0

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    quit_requested = False

    try:
        tty.setraw(fd)

        while queue and not quit_requested:
            cmd = queue[current_idx]

            while True:
                term_size = shutil.get_terminal_size()
                term_width = term_size.columns
                term_height = term_size.lines

                sys.stdout.write("\x1b[H\x1b[J")
                sys.stdout.write(
                    _render_flashcard(
                        cmd, current_idx + 1, len(queue),
                        correct, wrong, revealed,
                        term_width, term_height,
                    )
                )
                sys.stdout.flush()

                ch = sys.stdin.read(1)

                if ch == "\x1b":
                    quit_requested = True
                    break
                elif ch == "\x03":  # Ctrl-C
                    quit_requested = True
                    break

                if not revealed:
                    if ch in ("\r", "\n", " "):
                        revealed = True
                else:
                    if ch.lower() == "y":
                        correct += 1
                        queue.pop(current_idx)
                        revealed = False
                        if queue:
                            current_idx %= len(queue)
                        break  # next card
                    elif ch.lower() == "n":
                        wrong += 1
                        card = queue.pop(current_idx)
                        queue.append(card)
                        revealed = False
                        if queue:
                            current_idx %= len(queue)
                        break  # next card
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    # Show summary
    sys.stdout.write("\x1b[H\x1b[J")
    total = correct + wrong
    if total > 0:
        pct = correct * 100 // total
        summary = [
            "",
            f"  \x1b[1;36mFlashcard session complete\x1b[0m",
            "",
            f"  \x1b[32mCorrect: {correct}\x1b[0m",
            f"  \x1b[31mTo practice: {wrong}\x1b[0m",
            f"  \x1b[1;37mScore: {pct}%\x1b[0m",
            "",
            f"  Practiced {original_count} commands.",
            "",
        ]
        sys.stdout.write("\r\n".join(summary))
    else:
        sys.stdout.write("\r\n  No cards practiced.\r\n")
    sys.stdout.flush()
    # Wait for any key
    sys.stdin.read(1)
