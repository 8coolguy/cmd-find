"""Tests for cmd_find.mcp_server — tool handlers and protocol-level dispatch."""

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from cmd_find.mcp_server import (
    TOOLS,
    _fuzzy_match,
    _handle_search,
    _handle_list,
    _handle_get,
    _handle_fill,
    _send,
    run_server,
)
from cmd_find.scanner import ArgDef, Command

# ── Helpers to build synthetic Command objects ────────────────────────────────


def _cmd(description="test cmd", command="echo hello", tags=None, args=None, source="test.sh"):
    """Quick Command factory."""
    return Command(
        description=description,
        command=command,
        source_file=Path(source),
        tags=tags or [],
        args=args or [],
    )


def _arg(name, description="", type="text", default=""):
    """Quick ArgDef factory."""
    return ArgDef(name=name, description=description or name, type=type, default=default)


# ── Fuzzy matching ────────────────────────────────────────────────────────────


class TestFuzzyMatch(unittest.TestCase):
    """Tests for the _fuzzy_match scoring function."""

    def test_exact_match(self):
        score = _fuzzy_match("git", "git")
        self.assertGreater(score, 0)

    def test_empty_query_matches_everything(self):
        self.assertEqual(_fuzzy_match("", "anything"), 0.0)

    def test_no_match_returns_negative(self):
        self.assertEqual(_fuzzy_match("xyz", "abc"), -1.0)

    def test_substring_match(self):
        score = _fuzzy_match("git", "git rebase interactive")
        self.assertGreater(score, 0)

    def test_consecutive_match_bonus(self):
        """Consecutive character matches score higher than scattered."""
        score_consecutive = _fuzzy_match("git", "git")
        score_scattered = _fuzzy_match("git", "g_i_t")
        self.assertGreater(score_consecutive, score_scattered)

    def test_prefix_match_bonus(self):
        """First-character match gets a bonus."""
        score_prefix = _fuzzy_match("gi", "git rebase")
        score_mid = _fuzzy_match("gi", "rebase gi")
        self.assertGreater(score_prefix, score_mid)

    def test_case_insensitive(self):
        score = _fuzzy_match("GIT", "git")
        self.assertGreater(score, 0)

    def test_query_longer_than_text(self):
        self.assertEqual(_fuzzy_match("toolong", "short"), -1.0)


# ── Search handler ────────────────────────────────────────────────────────────


class TestHandleSearch(unittest.TestCase):
    """Tests for _handle_search."""

    def setUp(self):
        self.commands = [
            _cmd("Amend the last git commit", "git commit --amend", tags=["git", "fix"]),
            _cmd("List docker containers", "docker ps -a", tags=["docker"]),
            _cmd(
                "SSH into a server",
                "ssh -p {{port}} {{user}}@{{host}}",
                tags=["ssh"],
                args=[_arg("port", "Port", "number", "22"), _arg("user", "User"), _arg("host", "Host")],
            ),
            _cmd("Show git commit log with graph", "git log --oneline --graph", tags=["git", "log"]),
        ]

    def test_finds_matching_commands(self):
        result = _handle_search(self.commands, {"query": "git"})
        self.assertIn("Amend", result)
        self.assertIn("Show git commit log", result)
        self.assertNotIn("docker", result)
        self.assertNotIn("SSH", result)

    def test_ranks_better_matches_higher(self):
        """Results are sorted by score — better matches appear first."""
        result = _handle_search(self.commands, {"query": "git commit"})
        lines = result.split("\n")
        # "Amend the last git commit" should rank above "Show git commit log with graph"
        amend_idx = next(i for i, l in enumerate(lines) if "Amend" in l)
        log_idx = next(i for i, l in enumerate(lines) if "Show git commit log" in l)
        self.assertLess(amend_idx, log_idx)

    def test_no_match_message(self):
        result = _handle_search(self.commands, {"query": "kubernetes"})
        self.assertIn("No commands matched", result)
        self.assertIn("kubernetes", result)

    def test_empty_query_shows_message(self):
        result = _handle_search(self.commands, {"query": ""})
        self.assertIn("non-empty", result.lower())

    def test_includes_argument_definitions(self):
        result = _handle_search(self.commands, {"query": "ssh"})
        self.assertIn("@param port", result)
        self.assertIn("@param user", result)
        self.assertIn("@param host", result)
        self.assertIn("number", result)
        self.assertIn("22", result)  # default value

    def test_includes_arg_count_badge(self):
        result = _handle_search(self.commands, {"query": "ssh"})
        self.assertIn("(3 args)", result)

    def test_no_arg_count_for_static_commands(self):
        result = _handle_search(self.commands, {"query": "docker"})
        # "List docker containers" has no args — should not show "(0 args)"
        self.assertNotIn("(0 args)", result)

    def test_matches_against_tags(self):
        """Queries match against the tags field, not just description."""
        result = _handle_search(self.commands, {"query": "fix"})
        self.assertIn("Amend", result)

    def test_empty_commands_list(self):
        result = _handle_search([], {"query": "git"})
        self.assertIn("No commands matched", result)


# ── List handler ──────────────────────────────────────────────────────────────


class TestHandleList(unittest.TestCase):
    """Tests for _handle_list."""

    def setUp(self):
        self.commands = [
            _cmd("Git amend", "git commit --amend", source="/cmds/git/amend.sh"),
            _cmd("Git log", "git log", source="/cmds/git/log.sh"),
            _cmd("Docker ps", "docker ps", source="/cmds/docker/ps.sh"),
            _cmd("Docker prune", "docker system prune", source="/cmds/docker/prune.sh"),
        ]

    def test_lists_all_commands(self):
        result = _handle_list(self.commands, {})
        self.assertIn("Found 4 commands", result)
        self.assertIn("0.", result)
        self.assertIn("3.", result)

    def test_filter_by_path(self):
        result = _handle_list(self.commands, {"filter": "docker"})
        self.assertIn("Docker ps", result)
        self.assertIn("Docker prune", result)
        self.assertNotIn("Git amend", result)
        self.assertNotIn("Git log", result)

    def test_filter_no_match(self):
        result = _handle_list(self.commands, {"filter": "kubernetes"})
        self.assertIn("No commands found", result)
        self.assertIn("kubernetes", result)

    def test_empty_list(self):
        result = _handle_list([], {})
        self.assertIn("No commands found", result)

    def test_shows_arg_count(self):
        cmds = [
            _cmd("With args", "cmd {{x}}", source="a.sh", args=[_arg("x")]),
            _cmd("Static command", "cmd", source="b.sh"),
        ]
        result = _handle_list(cmds, {})
        self.assertIn("(1 args)", result)
        # "Without args" line should not have an args badge
        without_line = next(l for l in result.split("\n") if "Static command" in l)
        self.assertNotIn("args", without_line)


# ── Get handler ───────────────────────────────────────────────────────────────


class TestHandleGet(unittest.TestCase):
    """Tests for _handle_get."""

    def setUp(self):
        self.commands = [
            _cmd(
                "Git amend commit",
                "git commit --amend",
                tags=["git", "fix"],
                source="/cmds/git/amend.sh",
            ),
            _cmd(
                "SSH tunnel",
                "ssh -L {{port}}:localhost:{{port}} {{host}}",
                tags=["ssh", "tunnel"],
                source="/cmds/ssh/tunnel.sh",
                args=[
                    _arg("port", "Local port", "number", "5432"),
                    _arg("host", "Remote host", "text"),
                ],
            ),
        ]

    def test_valid_index_returns_details(self):
        result = _handle_get(self.commands, {"index": 0})
        self.assertIn("Index: 0", result)
        self.assertIn("Git amend commit", result)
        self.assertIn("git commit --amend", result)
        self.assertIn("git, fix", result)
        self.assertIn("/cmds/git/amend.sh", result)
        self.assertIn("(none — static command)", result)

    def test_shows_arguments_for_parameterised_command(self):
        result = _handle_get(self.commands, {"index": 1})
        self.assertIn("port", result)
        self.assertIn("number", result)
        self.assertIn("5432", result)
        self.assertIn("host", result)
        self.assertIn("[required]", result)  # host has no default

    def test_negative_index_out_of_range(self):
        result = _handle_get(self.commands, {"index": -1})
        self.assertIn("out of range", result)

    def test_index_too_high(self):
        result = _handle_get(self.commands, {"index": 99})
        self.assertIn("out of range", result)

    def test_empty_commands(self):
        result = _handle_get([], {"index": 0})
        self.assertIn("out of range", result)

    def test_default_missing_index(self):
        """No index provided → defaults to 0."""
        result = _handle_get(self.commands, {})
        self.assertIn("git commit --amend", result)


# ── Fill handler ──────────────────────────────────────────────────────────────


class TestHandleFill(unittest.TestCase):
    """Tests for _handle_fill."""

    def setUp(self):
        self.commands = [
            _cmd("Static command", "echo hello"),
            _cmd(
                "Parameterised",
                "git checkout -b {{branch}} {{base}}",
                args=[
                    _arg("branch", "Branch name"),
                    _arg("base", "Base branch", "text", "main"),
                ],
            ),
            _cmd(
                "With flag",
                "docker system prune {{force}}",
                args=[_arg("force", "Force removal", "flag")],
            ),
        ]

    def test_fill_substitutes_values(self):
        result = _handle_fill(self.commands, {
            "index": 1,
            "values": {"branch": "feature/x", "base": "develop"},
        })
        self.assertIn("git checkout -b feature/x develop", result)

    def test_fill_uses_default_for_missing(self):
        result = _handle_fill(self.commands, {
            "index": 1,
            "values": {"branch": "hotfix"},
        })
        self.assertIn("git checkout -b hotfix main", result)
        self.assertIn("default", result)

    def test_fill_with_int_value_converts_to_string(self):
        """JSON numbers are converted to strings for fill_command."""
        result = _handle_fill(self.commands, {
            "index": 1,
            "values": {"branch": "fix-42", "base": 42},
        })
        self.assertIn("fix-42 42", result)

    def test_fill_static_command(self):
        result = _handle_fill(self.commands, {"index": 0, "values": {}})
        self.assertIn("no arguments", result.lower())
        self.assertIn("echo hello", result)

    def test_fill_flag_truthy(self):
        result = _handle_fill(self.commands, {
            "index": 2,
            "values": {"force": "1"},
        })
        self.assertIn("force", result)

    def test_fill_flag_falsy(self):
        result = _handle_fill(self.commands, {
            "index": 2,
            "values": {"force": "0"},
        })
        self.assertNotIn("force", result.split("\n")[0])

    def test_out_of_range(self):
        result = _handle_fill(self.commands, {"index": 99, "values": {}})
        self.assertIn("out of range", result)

    def test_reports_required_for_unfilled(self):
        """Args without defaults and without provided values are flagged."""
        result = _handle_fill(self.commands, {
            "index": 1,
            "values": {},  # nothing provided
        })
        self.assertIn("required", result.lower())


# ── Protocol-level dispatch ───────────────────────────────────────────────────


class TestProtocolDispatch(unittest.TestCase):
    """Test the JSON-RPC dispatch loop — initialize, tools/list, tools/call, edge cases."""

    def _run(self, *json_lines: str) -> list[dict]:
        """Feed JSON-RPC requests to run_server and return captured responses."""
        input_stream = io.StringIO("\n".join(json_lines) + "\n")
        output = io.StringIO()

        with patch.object(sys, "stdin", input_stream), patch.object(sys, "stdout", output):
            run_server()

        lines = [l.strip() for l in output.getvalue().strip().split("\n") if l.strip()]
        return [json.loads(l) for l in lines]

    def test_initialize(self):
        responses = self._run(
            '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}',
        )
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["id"], 1)
        result = responses[0]["result"]
        self.assertEqual(result["protocolVersion"], "2024-11-05")
        self.assertEqual(result["serverInfo"]["name"], "cdfr")
        self.assertIn("tools", result["capabilities"])

    def test_tools_list(self):
        responses = self._run(
            '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}',
            '{"jsonrpc":"2.0","method":"notifications/initialized"}',
            '{"jsonrpc":"2.0","id":2,"method":"tools/list"}',
        )
        # Second response is tools/list (initialized is silent — no response)
        tools_resp = responses[1]  # 0=init, 1=tools/list
        tool_names = [t["name"] for t in tools_resp["result"]["tools"]]
        self.assertIn("search_commands", tool_names)
        self.assertIn("list_commands", tool_names)
        self.assertIn("get_command", tool_names)
        self.assertIn("fill_command", tool_names)

    def test_tools_call_search(self):
        responses = self._run(
            '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}',
            '{"jsonrpc":"2.0","method":"notifications/initialized"}',
            '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_commands","arguments":{"query":"x"}}}',
        )
        # Second response is the tool call result (initialized is silent)
        call_resp = responses[1]
        self.assertEqual(call_resp["id"], 2)
        self.assertIn("content", call_resp["result"])
        self.assertEqual(call_resp["result"]["content"][0]["type"], "text")

    def test_tools_call_unknown_tool(self):
        responses = self._run(
            '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}',
            '{"jsonrpc":"2.0","method":"notifications/initialized"}',
            '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"delete_everything","arguments":{}}}',
        )
        call_resp = responses[1]
        self.assertIn("error", call_resp)
        self.assertEqual(call_resp["error"]["code"], -32601)

    def test_ping(self):
        responses = self._run(
            '{"jsonrpc":"2.0","id":1,"method":"ping"}',
        )
        self.assertEqual(responses[0]["id"], 1)
        self.assertEqual(responses[0]["result"], {})

    def test_unknown_method(self):
        responses = self._run(
            '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}',
            '{"jsonrpc":"2.0","id":2,"method":"resources/list"}',
        )
        # resources/list is not supported
        err_resp = responses[1]
        self.assertIn("error", err_resp)
        self.assertEqual(err_resp["error"]["code"], -32601)

    def test_notifications_are_silent(self):
        """Notifications (no id) don't produce a response."""
        responses = self._run(
            '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}',
            '{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":1}}',
            '{"jsonrpc":"2.0","id":2,"method":"ping"}',
        )
        # Only init and ping should produce responses, not the notification
        ids = [r["id"] for r in responses]
        self.assertEqual(ids, [1, 2])

    def test_invalid_json_graceful(self):
        """Malformed JSON doesn't crash the server."""
        responses = self._run(
            '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}',
            "this is not json at all",
            '{"jsonrpc":"2.0","id":2,"method":"ping"}',
        )
        # Should get init response and ping response, skipping the garbage
        ids = [r["id"] for r in responses]
        self.assertEqual(ids, [1, 2])


# ── Tool schema validation ────────────────────────────────────────────────────


class TestToolSchemas(unittest.TestCase):
    """Verify the TOOLS list is well-formed MCP tool definitions."""

    def test_all_tools_have_name_and_description(self):
        for tool in TOOLS:
            self.assertIn("name", tool)
            self.assertIsInstance(tool["name"], str)
            self.assertIn("description", tool)
            self.assertIsInstance(tool["description"], str)

    def test_all_tools_have_input_schema(self):
        for tool in TOOLS:
            self.assertIn("inputSchema", tool)
            schema = tool["inputSchema"]
            self.assertEqual(schema["type"], "object")

    def test_search_requires_query(self):
        search = next(t for t in TOOLS if t["name"] == "search_commands")
        self.assertIn("query", search["inputSchema"]["required"])

    def test_get_requires_index(self):
        get_cmd = next(t for t in TOOLS if t["name"] == "get_command")
        self.assertIn("index", get_cmd["inputSchema"]["required"])

    def test_fill_requires_index_and_values(self):
        fill = next(t for t in TOOLS if t["name"] == "fill_command")
        self.assertIn("index", fill["inputSchema"]["required"])
        self.assertIn("values", fill["inputSchema"]["required"])

    def test_four_tools_registered(self):
        self.assertEqual(len(TOOLS), 4)


# ── JSON-RPC transport ────────────────────────────────────────────────────────


class TestTransport(unittest.TestCase):
    """Tests for the _send / response formatting."""

    def test_send_writes_valid_json(self):
        output = io.StringIO()
        with patch.object(sys, "stdout", output):
            _send({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})

        written = output.getvalue().strip()
        parsed = json.loads(written)
        self.assertEqual(parsed["jsonrpc"], "2.0")
        self.assertEqual(parsed["id"], 1)
        self.assertEqual(parsed["result"]["ok"], True)

    def test_send_flushes(self):
        """Each _send call ends with newline and is flushed (for line-delimited JSON)."""
        output = io.StringIO()
        with patch.object(sys, "stdout", output):
            _send({"jsonrpc": "2.0", "id": 1, "result": {}})

        self.assertTrue(output.getvalue().endswith("\n"))


if __name__ == "__main__":
    unittest.main()
