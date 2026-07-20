"""MCP server for cdfr — exposes curated shell commands to AI models.

Implements the Model Context Protocol (JSON-RPC 2.0 over stdio) so
MCP-compatible clients (Claude Code, Claude Desktop, etc.) can search
your command library, fill in templates, and suggest the right one-liner.

Protocol: https://modelcontextprotocol.io
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .config import DEFAULT_CONFIG_PATH, load_config
from .scanner import Command, fill_command, scan_directories


# ── JSON-RPC transport ────────────────────────────────────────────────────────

def _send(response: dict[str, Any]) -> None:
    """Write a JSON-RPC response to stdout (the MCP transport)."""
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def _log(message: str) -> None:
    """Log diagnostic messages to stderr so they don't corrupt the transport."""
    print(f"[cdfr-mcp] {message}", file=sys.stderr)


# ── Tool schema ───────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "search_commands",
        "description": (
            "Fuzzy-search your curated shell command library. "
            "Matches against command descriptions and tags. "
            "Returns ranked results with the command template and any parameter definitions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Free-text search query to match against command descriptions and tags.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_commands",
        "description": (
            "List all available shell commands in your curated library. "
            "Use an optional path filter to narrow results (e.g. 'git' to show only "
            "commands under a git/ subdirectory)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": "Optional path substring filter — only show commands whose source file path contains this string.",
                },
            },
        },
    },
    {
        "name": "get_command",
        "description": (
            "Get the full details of a specific command by its index (from list_commands). "
            "Returns the description, command template, tags, source file, and any "
            "@param argument definitions with their types and defaults."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "index": {
                    "type": "integer",
                    "description": "Zero-based index of the command from list_commands ordering.",
                },
            },
            "required": ["index"],
        },
    },
    {
        "name": "fill_command",
        "description": (
            "Fill in the arguments of a parameterised command template and return "
            "the completed, ready-to-run shell command. Get the index from "
            "list_commands, then provide values keyed by argument name. "
            "Omitted arguments fall back to their declared defaults."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "index": {
                    "type": "integer",
                    "description": "Zero-based index of the command from list_commands ordering.",
                },
                "values": {
                    "type": "object",
                    "description": "Mapping of argument name → value for each {{placeholder}} in the template.",
                },
            },
            "required": ["index", "values"],
        },
    },
]

SERVER_INFO = {
    "name": "cdfr",
    "version": "1.0.0",
}


# ── Command loading ───────────────────────────────────────────────────────────

def _load_commands(config_path: str | None = None) -> list[Command]:
    """Load all commands from the configured directories."""
    config = load_config(Path(config_path) if config_path else None)
    return scan_directories(config.directories)


# ── Tool handlers ─────────────────────────────────────────────────────────────

def _fuzzy_match(query: str, text: str) -> float:
    """Score how well `query` fuzzy-matches `text`.

    Higher is better. Returns -1 for no match.
    Consecutive and prefix character matches get bonus points.
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
            if ti == prev_match + 1:
                score += 2.0   # consecutive
            elif ti == 0:
                score += 1.5   # prefix
            else:
                score += 1.0
            prev_match = ti
            qi += 1

    if qi < len(query):
        return -1.0

    return score


def _handle_search(commands: list[Command], arguments: dict[str, Any]) -> str:
    """Fuzzy-search commands and return ranked matches."""
    query = arguments.get("query", "")
    if not query.strip():
        return "Please provide a non-empty search query."

    scored: list[tuple[float, int, Command]] = []
    for i, cmd in enumerate(commands):
        search_text = cmd.description
        if cmd.tags:
            search_text += " " + " ".join(cmd.tags)
        score = _fuzzy_match(query, search_text)
        if score >= 0:
            scored.append((score, i, cmd))

    scored.sort(key=lambda x: (-x[0], x[1]))

    if not scored:
        return f"No commands matched '{query}'."

    lines: list[str] = []
    for rank, (_score, _orig_idx, cmd) in enumerate(scored[:20]):
        tag_str = f"[{','.join(cmd.tags)}] " if cmd.tags else ""
        args_note = f" ({len(cmd.args)} args)" if cmd.has_args else ""
        lines.append(f"{rank}. {tag_str}{cmd.description}{args_note}")
        lines.append(f"   {cmd.command}")
        if cmd.args:
            for a in cmd.args:
                default_note = f" (default: {a.default})" if a.default else ""
                lines.append(f"     @param {a.name}: {a.description} [{a.type}]{default_note}")

    if len(scored) > 20:
        lines.append(f"\n... and {len(scored) - 20} more matches.")

    return "\n".join(lines)


def _handle_list(commands: list[Command], arguments: dict[str, Any]) -> str:
    """List all commands, with optional path filter."""
    filter_str = arguments.get("filter", "")
    if filter_str:
        needle = filter_str.lower()
        filtered = [c for c in commands if needle in str(c.source_file).lower()]
    else:
        filtered = list(commands)

    if not filtered:
        msg = "No commands found"
        if filter_str:
            msg += f" matching filter '{filter_str}'"
        return msg + "."

    lines = [f"Found {len(filtered)} commands:"]
    for i, cmd in enumerate(filtered):
        tag_str = f"[{','.join(cmd.tags)}] " if cmd.tags else ""
        args_note = f" ({len(cmd.args)} args)" if cmd.has_args else ""
        lines.append(f"{i}. {tag_str}{cmd.description}{args_note}")
        lines.append(f"   {cmd.command}")

    return "\n".join(lines)


def _handle_get(commands: list[Command], arguments: dict[str, Any]) -> str:
    """Return full details for one command by index."""
    index = arguments.get("index", 0)
    if index < 0 or index >= len(commands):
        return f"Index {index} is out of range. Valid range: 0–{len(commands) - 1}."

    cmd = commands[index]
    lines = [
        f"Index: {index}",
        f"Description: {cmd.description}",
        f"Command: {cmd.command}",
        f"Tags: {', '.join(cmd.tags) if cmd.tags else '(none)'}",
        f"Source: {cmd.source_file}",
    ]
    if cmd.args:
        lines.append("Arguments:")
        for a in cmd.args:
            default_note = f" (default: {a.default})" if a.default else ""
            required = "" if a.default else " [required]"
            lines.append(f"  • {a.name}: {a.description} [{a.type}]{default_note}{required}")
    else:
        lines.append("Arguments: (none — static command)")

    return "\n".join(lines)


def _handle_fill(commands: list[Command], arguments: dict[str, Any]) -> str:
    """Substitute {{placeholders}} with user-provided values."""
    index = arguments.get("index", 0)
    if index < 0 or index >= len(commands):
        return f"Index {index} is out of range. Valid range: 0–{len(commands) - 1}."

    cmd = commands[index]
    if not cmd.has_args:
        return f"This command has no arguments. Run it directly:\n\n  {cmd.command}"

    values: dict[str, str] = arguments.get("values", {})

    # Convert number values to strings (they come as int/float from JSON)
    str_values: dict[str, str] = {}
    for k, v in values.items():
        str_values[k] = str(v)

    filled = fill_command(cmd, str_values)

    parts = [f"{filled}\n"]
    for arg in cmd.args:
        if arg.name in str_values:
            parts.append(f"  • {arg.name} = '{str_values[arg.name]}' (provided)")
        elif arg.default:
            parts.append(f"  • {arg.name} = '{arg.default}' (default)")
        else:
            parts.append(f"  • {arg.name} = (not set — required!)")

    return "\n".join(parts)


# ── Main dispatch loop ────────────────────────────────────────────────────────

def run_server(config_path: str | None = None) -> None:
    """Run the MCP server over stdio (JSON-RPC 2.0).

    Reads JSON-RPC requests line-by-line from stdin, dispatches to
    the appropriate handler, and writes responses to stdout.

    Set by Claude Code / MCP client — no user interaction needed:
        {
          "mcpServers": {
            "cdfr": {
              "command": "python",
              "args": ["-m", "cmd_find.mcp_server"]
            }
          }
        }
    """
    _log("Starting cdfr MCP server...")

    commands: list[Command] = []
    initialized = False

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            _log(f"Invalid JSON from client: {exc}")
            continue

        req_id = request.get("id")
        method = request.get("method", "")

        # ── initialize ───────────────────────────────────────────────────
        if method == "initialize":
            _send({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": SERVER_INFO,
                    "capabilities": {"tools": {}},
                },
            })
            initialized = True
            _log("Handshake complete.")

        # ── notifications/initialized ────────────────────────────────────
        elif method == "notifications/initialized":
            commands = _load_commands(config_path)
            _log(f"Loaded {len(commands)} commands from configured directories.")

        # ── tools/list ────────────────────────────────────────────────────
        elif method == "tools/list":
            _send({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": TOOLS},
            })

        # ── tools/call ────────────────────────────────────────────────────
        elif method == "tools/call":
            params = request.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            handler_map: dict[str, Any] = {
                "search_commands": _handle_search,
                "list_commands": _handle_list,
                "get_command": _handle_get,
                "fill_command": _handle_fill,
            }

            handler = handler_map.get(tool_name)
            if handler is None:
                _send({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Unknown tool: {tool_name}",
                    },
                })
                continue

            try:
                result_text = handler(commands, arguments)
                _send({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": result_text},
                        ],
                    },
                })
            except Exception as exc:
                _log(f"Error in {tool_name}: {exc}")
                _send({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": f"Error: {exc}"},
                        ],
                        "isError": True,
                    },
                })

        # ── ping ──────────────────────────────────────────────────────────
        elif method == "ping":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {}})

        # ── notifications/cancelled, etc. ─────────────────────────────────
        elif method.startswith("notifications/"):
            pass  # acknowledge silently

        # ── unknown ───────────────────────────────────────────────────────
        else:
            _send({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Unknown method: {method}",
                },
            })

    _log("Server stopped.")


if __name__ == "__main__":
    run_server()
