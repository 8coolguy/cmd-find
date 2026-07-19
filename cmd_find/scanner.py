"""Scan directories for templated .sh command files."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class ArgDef:
    """Definition of a command argument."""

    name: str            # placeholder name, e.g. "branch_name"
    description: str     # human-readable label, e.g. "Branch name"
    type: str = "text"   # text | number | path | flag | choice:opt1,opt2,...
    default: str = ""    # default value (empty = required)


@dataclass
class Command:
    """A single command entry with its metadata and argument definitions."""

    description: str          # joined comment lines
    command: str              # the one-liner shell command (may contain {{placeholders}})
    source_file: Path         # which .sh file this came from
    tags: List[str] = field(default_factory=list)
    args: List[ArgDef] = field(default_factory=list)

    @property
    def has_args(self) -> bool:
        return len(self.args) > 0


def _parse_arg(line: str) -> ArgDef | None:
    """Parse an @param line like:
        # @param name | description | type | default
    Returns None if the line doesn't match.
    """
    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 2:
        return None

    name = parts[0]
    description = parts[1]
    arg_type = parts[2] if len(parts) > 2 else "text"
    default = parts[3] if len(parts) > 3 else ""

    return ArgDef(name=name, description=description, type=arg_type, default=default)


def _parse_script(filepath: Path) -> Command | None:
    """Parse a .sh file into a Command.

    - Lines starting with '# @param' declare an argument:
        # @param name | Label | type | default
      Types: text, number, path, flag, choice:a,b,c
    - Lines starting with '# Tags:' or '# tags:' populate tags.
    - Other '#' lines are collected as the description.
    - The first non-empty, non-comment line becomes the command template.
    - Everything after the first command line is ignored.
    """
    with open(filepath) as f:
        lines = f.readlines()

    comments: List[str] = []
    tags: List[str] = []
    args: List[ArgDef] = []
    command: str | None = None

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue

        if stripped.startswith("#"):
            content = stripped[1:].strip()

            # @param lines
            if content.lower().startswith("@param ") or content.lower().startswith("@arg "):
                # Strip the prefix
                prefix_len = 7 if content.lower().startswith("@param ") else 5
                arg_def = _parse_arg(content[prefix_len:])
                if arg_def:
                    args.append(arg_def)
                continue

            # Tag lines
            if content.lower().startswith("tags:"):
                tag_part = content[5:].strip()
                tags.extend(t.strip() for t in tag_part.split(",") if t.strip())
                continue
            elif content.lower().startswith("tag:"):
                tag_part = content[4:].strip()
                tags.extend(t.strip() for t in tag_part.split(",") if t.strip())
                continue

            # Regular comment
            comments.append(content)
            continue

        # First non-comment, non-empty line is the command
        if command is None:
            command = stripped
            break  # only take the first command line

    if command is None:
        return None  # no command found

    description = " ".join(comments).strip()
    if not description:
        description = filepath.stem.replace("-", " ").replace("_", " ")

    return Command(
        description=description,
        command=command,
        source_file=filepath,
        tags=tags,
        args=args,
    )


def scan_directories(dirs: List[Path]) -> List[Command]:
    """Scan all configured directories for .sh files and parse them.

    Returns a list of Command objects. Directories that don't exist
    are silently skipped.
    """
    commands: List[Command] = []

    for d in dirs:
        if not d.is_dir():
            continue
        for fpath in sorted(d.rglob("*.sh")):
            if not fpath.is_file():
                continue
            cmd = _parse_script(fpath)
            if cmd is not None:
                commands.append(cmd)

    return commands


def fill_command(command: Command, values: dict[str, str]) -> str:
    """Substitute {{placeholders}} in the command template with user values.

    Performs replacement in two phases:
      1. Build a lookup of all resolved values (user-provided or default).
      2. Repeatedly replace all {{name}} tokens until stable (handles
         cross-references like 'pr-{{other_arg}}' in defaults).
    """
    import re

    # Phase 1: resolve all values
    resolved: dict[str, str] = {}
    for arg in command.args:
        val = values.get(arg.name, arg.default)

        if arg.type == "flag":
            if val.strip().lower() in ("", "0", "false", "no"):
                val = ""
            elif val.strip().lower() in ("1", "true", "yes"):
                val = arg.name

        resolved[arg.name] = val

    # Phase 2: repeatedly substitute until stable
    result = command.command
    for _ in range(len(command.args) + 1):  # at most N+1 passes
        prev = result
        for name, val in resolved.items():
            result = result.replace("{{" + name + "}}", val)
        if result == prev:
            break

    # Clean up any remaining unresolved {{...}} tokens
    result = re.sub(r"\{\{.*?\}\}", "", result)
    # Collapse multiple spaces
    result = re.sub(r"  +", " ", result).strip()

    return result
