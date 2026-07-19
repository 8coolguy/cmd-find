"""Entry point for the cmd-find CLI tool."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from .config import Config, create_default_config, load_config
from .finder import run_finder, _fill_args, flashcard_mode
from .scanner import fill_command, scan_directories


def _copy_to_clipboard(text: str) -> bool:
    """Copy text to the system clipboard.

    Tries multiple platform-specific tools. Returns True on success.
    """
    tools = [
        ("wl-copy", ["wl-copy"], {}),
        ("xclip", ["xclip", "-selection", "clipboard"], {}),
        ("xsel", ["xsel", "--clipboard", "--input"], {}),
        ("pbcopy", ["pbcopy"], {}),
        ("clip.exe", ["clip.exe"], {}),
    ]

    for name, cmd, kwargs in tools:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(
                    cmd, input=text, text=True, timeout=5, **kwargs
                )
                return True
            except (subprocess.TimeoutExpired, OSError):
                continue

    return False


def _resolve_mode(args, config: Config) -> str:
    """Determine the effective output mode.

    CLI flags take priority over the config default.
    If multiple flags are given, --exec wins over --copy wins over --print.
    """
    if args.exec:
        return "exec"
    if args.copy:
        return "copy"
    if args.print_mode:
        return "print"
    return config.mode


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cmd-find",
        description="Fuzzy-find templated shell commands from curated directories.",
    )
    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=None,
        help="Path to config file (default: ~/.config/cmd-find/config.toml)",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Create a default config file and exit",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available commands without interactive mode",
    )
    parser.add_argument(
        "--exec",
        action="store_true",
        help="Execute the selected command directly (overrides config default)",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy the selected command to the clipboard (overrides config default)",
    )
    parser.add_argument(
        "--print",
        dest="print_mode",
        action="store_true",
        help="Print the selected command to stdout (overrides config default)",
    )
    parser.add_argument(
        "--flash",
        action="store_true",
        help="Flashcard mode — practice memorising commands",
    )
    parser.add_argument(
        "filter",
        nargs="?",
        default=None,
        help="Only show commands from files/directories whose path contains this string",
    )
    args = parser.parse_args()

    if args.init:
        create_default_config()
        return

    config = load_config(args.config)

    if not config.directories:
        print(
            "cmd-find: No directories configured.",
            file=sys.stderr,
        )
        print(
            f"Run 'cmd-find --init' to create a default config, or edit "
            f"~/.config/cmd-find/config.toml",
            file=sys.stderr,
        )
        sys.exit(1)

    commands = scan_directories(config.directories)

    # Apply path filter
    if args.filter:
        needle = args.filter.lower()
        commands = [
            c for c in commands
            if needle in str(c.source_file).lower()
        ]
        if not commands:
            print(
                f"cmd-find: No commands matched filter '{args.filter}'.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Where to save new commands
    save_dir = config.directories[0] if config.directories else (
        Path.home() / ".local" / "share" / "cmd-find" / "commands"
    )

    if args.list:
        for cmd in commands:
            tag_str = f"[{','.join(cmd.tags)}] " if cmd.tags else ""
            print(f"  {tag_str}{cmd.description}")
            print(f"    → {cmd.command}")
            if cmd.args:
                for a in cmd.args:
                    default_note = f" (default: {a.default})" if a.default else ""
                    print(f"      @param {a.name}: {a.description} [{a.type}]{default_note}")
            print(f"    source: {cmd.source_file}")
            print()
        return

    if args.flash:
        flashcard_mode(commands)
        return

    selected = run_finder(commands, save_dir)

    if selected is None:
        sys.exit(130)

    final_command = selected.command
    if selected.has_args:
        values = _fill_args(selected)
        if values is None:
            sys.exit(130)
        final_command = fill_command(selected, values)

    # Resolve and apply output mode
    mode = _resolve_mode(args, config)

    if mode == "exec":
        subprocess.run(final_command, shell=True)
    elif mode == "copy":
        if _copy_to_clipboard(final_command):
            print(f"Copied: {final_command}", file=sys.stderr)
        else:
            print(
                "cmd-find: No clipboard tool found. Install xclip, xsel, or wl-copy.",
                file=sys.stderr,
            )
            print(final_command)
            sys.exit(1)
    else:
        # mode == "print"
        sys.stdout.write(final_command + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
