"""Configuration handling for cdfr."""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Literal

OutputMode = Literal["print", "copy", "exec"]


@dataclass
class Config:
    """Parsed cdfr configuration."""
    directories: List[Path] = field(default_factory=list)
    mode: OutputMode = "print"


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "cdfr" / "config.toml"


def _expand(path_str: str) -> Path:
    """Expand ~ and environment variables in a path string."""
    return Path(os.path.expandvars(os.path.expanduser(path_str))).resolve()


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from the TOML config file.

    Returns a Config with directories (unique, preserving order) and mode.
    Falls back to defaults if the config file doesn't exist.
    """
    path = config_path or DEFAULT_CONFIG_PATH

    if not path.exists():
        return Config()

    with open(path, "rb") as f:
        data = tomllib.load(f)

    raw: List[str] = data.get("directories", [])

    # Deduplicate while preserving order
    seen = set()
    dirs: List[Path] = []
    for d in raw:
        resolved = _expand(d)
        if resolved not in seen:
            seen.add(resolved)
            dirs.append(resolved)

    mode_raw = data.get("mode", "print")
    mode: OutputMode = mode_raw if mode_raw in ("print", "copy", "exec") else "print"

    return Config(directories=dirs, mode=mode)


def create_default_config(path: Path | None = None) -> Path:
    """Create a default config file and return its path."""
    target = path or DEFAULT_CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    default_dir = Path.home() / ".local" / "share" / "cdfr" / "commands"
    default_dir.mkdir(parents=True, exist_ok=True)

    content = f'''# cdfr configuration
# List directories containing your templated .sh command files.
# Paths support ~ and $ENV_VAR expansion.

directories = [
    "{default_dir}",
]

# Default output mode when no flag is given.
#   "print" — output to stdout (for shell integration / Ctrl+F)
#   "copy"  — copy to system clipboard
#   "exec"  — execute immediately
mode = "print"
'''
    target.write_text(content)
    print(f"Created default config at: {target}")
    print(f"Created default commands dir at: {default_dir}")
    return target
