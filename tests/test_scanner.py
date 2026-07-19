"""Tests for cmd_find.scanner — .sh file parsing and directory scanning."""

from pathlib import Path
import unittest

from cmd_find.scanner import scan_directories, Command

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "commands"


class TestScannerParsing(unittest.TestCase):
    """Test individual command file parsing via scan_directories."""

    def _scan(self, subpath: str = ".") -> list[Command]:
        """Helper: scan a subdirectory of the fixtures."""
        return scan_directories([FIXTURES / subpath])

    def _find(self, commands: list[Command], stem: str) -> Command:
        """Find a command by source file stem."""
        for c in commands:
            if c.source_file.stem == stem:
                return c
        raise AssertionError(f"Command with stem '{stem}' not found")

    # ── Description parsing ─────────────────────────────────────────────

    def test_multiple_comment_lines(self):
        """Multiple # lines are joined into one description."""
        cmds = self._scan("git")
        cmd = self._find(cmds, "new-branch")
        self.assertIn("standard command", cmd.description)
        self.assertIn("create a new git branch", cmd.description)

    def test_single_comment_line(self):
        """A single comment line becomes the description."""
        cmds = self._scan("git")
        cmd = self._find(cmds, "rebase")
        self.assertEqual(cmd.description, "Single-line description")

    def test_no_description_fallback_to_filename(self):
        """No comment lines → description falls back to the filename stem."""
        cmds = self._scan()
        cmd = self._find(cmds, "no-description")
        self.assertEqual(cmd.description, "no description")

    # ── Command extraction ──────────────────────────────────────────────

    def test_extracts_first_command_line(self):
        """Only the first non-comment, non-empty line becomes the command."""
        cmds = self._scan("git")
        cmd = self._find(cmds, "status")
        # The file has "git status" first, "git log" second
        self.assertEqual(cmd.command, "git status")

    def test_command_with_pipes_and_vars(self):
        """Commands with pipes and $VARS are preserved exactly."""
        cmds = self._scan("docker")
        cmd = self._find(cmds, "cleanup")
        self.assertEqual(cmd.command, 'docker ps -aq | xargs docker rm -f $FLAG')

    def test_skips_empty_lines_before_command(self):
        """Empty lines before the command are ignored."""
        cmds = self._scan("docker")
        cmd = self._find(cmds, "exec")
        self.assertEqual(cmd.command, 'docker exec -it $CONTAINER /bin/bash')

    def test_skips_file_with_no_command(self):
        """A file with only comments and no command is excluded."""
        cmds = self._scan("docker")
        stems = {c.source_file.stem for c in cmds}
        self.assertNotIn("no-command", stems)

    # ── Tag parsing ─────────────────────────────────────────────────────

    def test_tags_plural_format(self):
        """# Tags: foo, bar  → tags list."""
        cmds = self._scan("git")
        cmd = self._find(cmds, "new-branch")
        self.assertEqual(cmd.tags, ["git", "branch"])

    def test_tags_singular_format(self):
        """# Tag: foo, bar  → tags list (singular form)."""
        cmds = self._scan()
        cmd = self._find(cmds, "db-backup")
        self.assertEqual(cmd.tags, ["db", "postgres", "backup"])

    def test_single_tag(self):
        """# Tag: single-tag-only  → one-element list."""
        cmds = self._scan("git")
        cmd = self._find(cmds, "stash")
        self.assertEqual(cmd.tags, ["single-tag-only"])

    def test_tags_with_spaces(self):
        """Tags with irregular spacing are trimmed."""
        cmds = self._scan("git")
        cmd = self._find(cmds, "undo")
        self.assertEqual(cmd.tags, ["git", "undo", "fix"])

    # ── Directory scanning ──────────────────────────────────────────────

    def test_recursive_scan(self):
        """Deeply nested .sh files are found."""
        cmds = self._scan("nested")
        stems = {c.source_file.stem for c in cmds}
        self.assertIn("buried", stems)
        cmd = self._find(cmds, "buried")
        self.assertEqual(cmd.command, 'echo "found me deep in the tree"')
        self.assertEqual(cmd.tags, ["deep", "nested", "test"])

    def test_ignores_non_sh_files(self):
        """.txt files are not scanned."""
        cmds = self._scan()
        stems = {c.source_file.stem for c in cmds}
        self.assertNotIn("not-a-script", stems)

    def test_ignores_empty_directory(self):
        """An empty directory produces no commands (doesn't crash)."""
        empty = FIXTURES.parent / "empty-dir"
        cmds = scan_directories([empty])
        self.assertEqual(cmds, [])

    def test_missing_directory_silently_skipped(self):
        """A nonexistent directory doesn't crash the scanner."""
        cmds = scan_directories([Path("/tmp/definitely-does-not-exist-xyz")])
        self.assertEqual(cmds, [])

    # ── Command count ───────────────────────────────────────────────────

    def test_total_command_count(self):
        """Verify we find exactly the right number of valid commands."""
        cmds = self._scan()
        # 11 fixture .sh files, minus 1 (no-command.sh) = 10 commands
        self.assertEqual(len(cmds), 10)

    def test_commands_have_source_file(self):
        """Every command records its source .sh file."""
        cmds = self._scan()
        for c in cmds:
            self.assertTrue(c.source_file.is_file())
            self.assertTrue(c.source_file.suffix == ".sh")

    def test_commands_have_non_empty_command(self):
        """Every returned command has a non-empty command string."""
        cmds = self._scan()
        for c in cmds:
            self.assertIsInstance(c.command, str)
            self.assertTrue(len(c.command) > 0)

    def test_commands_have_non_empty_description(self):
        """Every returned command has a non-empty description string."""
        cmds = self._scan()
        for c in cmds:
            self.assertIsInstance(c.description, str)
            self.assertTrue(len(c.description) > 0)


class TestArgParsing(unittest.TestCase):
    """Test @param parsing and fill_command substitution."""

    @staticmethod
    def _parse(text: str):
        """Parse a single .sh text blob and return the Command."""
        import tempfile, os
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write(text)
            f.flush()
            name = f.name
        try:
            cmds = scan_directories([Path(name).parent])
            for c in cmds:
                if c.source_file == Path(name):
                    return c
            raise AssertionError("Command not found")
        finally:
            os.unlink(name)

    def test_parses_single_param(self):
        """A single @param line creates one ArgDef."""
        cmd = self._parse("""\
# Description
# @param name | Your name | text
echo Hello {{name}}
""")
        self.assertEqual(len(cmd.args), 1)
        self.assertEqual(cmd.args[0].name, "name")
        self.assertEqual(cmd.args[0].description, "Your name")
        self.assertEqual(cmd.args[0].type, "text")
        self.assertEqual(cmd.args[0].default, "")

    def test_parses_param_with_default(self):
        """A @param with four parts includes a default."""
        cmd = self._parse("""\
# @param branch | Branch name | text | main
git checkout -b {{branch}}
""")
        self.assertEqual(cmd.args[0].default, "main")

    def test_parses_multiple_params(self):
        """Multiple @param lines in order."""
        cmd = self._parse("""\
# @param host | Hostname | text
# @param port | Port number | number | 22
ssh -p {{port}} {{host}}
""")
        self.assertEqual(len(cmd.args), 2)
        self.assertEqual(cmd.args[0].name, "host")
        self.assertEqual(cmd.args[1].name, "port")
        self.assertEqual(cmd.args[1].type, "number")

    def test_parses_choice_type(self):
        """choice:opt1,opt2,opt3 format."""
        cmd = self._parse("""\
# @param shell | Shell | choice:bash,zsh,sh | bash
docker exec -it c /bin/{{shell}}
""")
        self.assertEqual(cmd.args[0].type, "choice:bash,zsh,sh")

    def test_arg_not_in_description(self):
        """@param lines are excluded from the description."""
        cmd = self._parse("""\
# A great command
# @param x | Something | text
echo {{x}}
""")
        self.assertEqual(cmd.description, "A great command")
        self.assertNotIn("@param", cmd.description)

    def test_tags_and_args_coexist(self):
        """Tags and @param can both be present."""
        cmd = self._parse("""\
# Tags: git, branch
# @param name | Branch name | text
git checkout -b {{name}}
""")
        self.assertEqual(cmd.tags, ["git", "branch"])
        self.assertEqual(len(cmd.args), 1)

    def test_has_args_property(self):
        """Command.has_args reflects whether args exist."""
        with_args = self._parse("""\
# @param x | X | text
echo {{x}}
""")
        without_args = self._parse("""\
echo hello
""")
        self.assertTrue(with_args.has_args)
        self.assertFalse(without_args.has_args)


class TestFillCommand(unittest.TestCase):
    """Test the fill_command substitution function."""

    def test_simple_substitution(self):
        """{{var}} is replaced with the value."""
        from cmd_find.scanner import fill_command, ArgDef, Command
        cmd = Command(
            description="test",
            command="echo {{name}}",
            source_file=Path("/tmp/test.sh"),
            args=[ArgDef(name="name", description="Name", type="text")],
        )
        result = fill_command(cmd, {"name": "Alice"})
        self.assertEqual(result, "echo Alice")

    def test_default_used_when_missing(self):
        """When a value is missing, the default is used."""
        from cmd_find.scanner import fill_command, ArgDef, Command
        cmd = Command(
            description="test",
            command="git checkout -b {{branch}} {{base}}",
            source_file=Path("/tmp/test.sh"),
            args=[
                ArgDef(name="branch", description="Branch", type="text"),
                ArgDef(name="base", description="Base", type="text", default="main"),
            ],
        )
        result = fill_command(cmd, {"branch": "feature/x"})
        self.assertEqual(result, "git checkout -b feature/x main")

    def test_flag_type_true(self):
        """Flag with truthy value inserts the flag name."""
        from cmd_find.scanner import fill_command, ArgDef, Command
        cmd = Command(
            description="test",
            command="docker system prune {{force}}",
            source_file=Path("/tmp/test.sh"),
            args=[ArgDef(name="force", description="Force", type="flag")],
        )
        result = fill_command(cmd, {"force": "1"})
        self.assertEqual(result, "docker system prune force")

    def test_flag_type_false_removes_placeholder(self):
        """Flag with falsy value removes the placeholder entirely."""
        from cmd_find.scanner import fill_command, ArgDef, Command
        cmd = Command(
            description="test",
            command="docker ps {{all}}",
            source_file=Path("/tmp/test.sh"),
            args=[ArgDef(name="all", description="Show all", type="flag")],
        )
        result = fill_command(cmd, {"all": "0"})
        self.assertEqual(result, "docker ps")

    def test_remaining_placeholders_cleaned(self):
        """Unfilled {{placeholders}} are removed from the output."""
        from cmd_find.scanner import fill_command
        from cmd_find.scanner import Command, ArgDef
        cmd = Command(
            description="test",
            command="echo {{greeting}} {{name}}",
            source_file=Path("/tmp/test.sh"),
            args=[
                ArgDef(name="greeting", description="Greeting", type="text"),
            ],
        )
        result = fill_command(cmd, {"greeting": "Hello"})
        self.assertEqual(result, "echo Hello")

    def test_multiple_spaces_collapsed(self):
        """Extra spaces from removed placeholders are collapsed."""
        from cmd_find.scanner import fill_command
        from cmd_find.scanner import Command, ArgDef
        cmd = Command(
            description="test",
            command="cmd {{a}}  {{b}}  {{c}}",
            source_file=Path("/tmp/test.sh"),
            args=[
                ArgDef(name="a", description="A", type="text"),
            ],
        )
        result = fill_command(cmd, {"a": "x"})
        self.assertEqual(result, "cmd x")

    def test_cross_reference_default(self):
        """A default referencing another arg name resolves correctly."""
        from cmd_find.scanner import fill_command, Command, ArgDef
        cmd = Command(
            description="test",
            command="git fetch pr/{{num}}/head:{{branch}}",
            source_file=Path("/tmp/test.sh"),
            args=[
                ArgDef(name="num", description="PR number", type="number"),
                ArgDef(name="branch", description="Branch", type="text", default="pr-{{num}}"),
            ],
        )
        result = fill_command(cmd, {"num": "42"})
        self.assertEqual(result, "git fetch pr/42/head:pr-42")


if __name__ == "__main__":
    unittest.main()
