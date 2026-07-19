"""Integration tests — run cmd-find as a subprocess end-to-end."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


CMD_FIND = [sys.executable, "-m", "cmd_find.main"]


class TestIntegration(unittest.TestCase):
    """End-to-end tests invoking cmd-find as a subprocess."""

    def setUp(self):
        """Create a temporary config pointing at our fixture commands."""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmpdir.name) / "config.toml"

        fixtures = (
            Path(__file__).resolve().parent / "fixtures" / "commands"
        )
        self.config_path.write_text(
            f'directories = ["{fixtures}"]\n'
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _run(self, *extra_args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*CMD_FIND, "-c", str(self.config_path), *extra_args],
            capture_output=True,
            text=True,
        )

    # ── CLI flags ───────────────────────────────────────────────────────

    def test_help_flag(self):
        """--help prints usage and exits 0."""
        proc = self._run("--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Fuzzy-find", proc.stdout)

    def test_init_flag(self):
        """--init creates config and prints message."""
        proc = self._run("--init")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Created default config", proc.stdout)

    # ── --list output ───────────────────────────────────────────────────

    def test_list_output_is_not_empty(self):
        """--list outputs all commands."""
        proc = self._run("--list")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("new-branch", proc.stdout)
        self.assertIn("docker", proc.stdout)

    def test_list_includes_descriptions(self):
        """--list includes description text."""
        proc = self._run("--list")
        self.assertIn("Single-line description", proc.stdout)

    def test_list_includes_commands(self):
        """--list includes the command text."""
        proc = self._run("--list")
        self.assertIn("git rebase -i HEAD~3", proc.stdout)

    def test_list_includes_tags(self):
        """--list includes tag badges."""
        proc = self._run("--list")
        self.assertIn("[git,branch]", proc.stdout)

    def test_list_includes_source_file(self):
        """--list shows the source file path."""
        proc = self._run("--list")
        self.assertIn("source:", proc.stdout)
        self.assertIn("new-branch.sh", proc.stdout)

    def test_list_does_not_include_no_command_file(self):
        """--list excludes files with no command."""
        proc = self._run("--list")
        self.assertNotIn("no-command", proc.stdout)

    def test_list_includes_nested_files(self):
        """--list finds deeply nested commands."""
        proc = self._run("--list")
        self.assertIn("buried", proc.stdout)
        self.assertIn("found me deep", proc.stdout)

    # ── Error handling ──────────────────────────────────────────────────

    def test_no_config_no_dirs_exits_with_error(self):
        """When config has no dirs and no --init, exit 1 with message."""
        empty_cfg = Path(self.tmpdir.name) / "empty.toml"
        empty_cfg.write_text("directories = []\n")
        proc = subprocess.run(
            [*CMD_FIND, "-c", str(empty_cfg), "--list"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("No directories configured", proc.stderr)

    def test_missing_directories_dont_crash_list(self):
        """If a configured directory doesn't exist, --list still works."""
        cfg = Path(self.tmpdir.name) / "with_missing.toml"
        fixtures = (
            Path(__file__).resolve().parent / "fixtures" / "commands"
        )
        cfg.write_text(
            f'directories = ["/tmp/does-not-exist-xyz-123", "{fixtures}"]\n'
        )
        proc = subprocess.run(
            [*CMD_FIND, "-c", str(cfg), "--list"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("new-branch", proc.stdout)

    # ── Ordered output ──────────────────────────────────────────────────

    def test_list_output_is_ordered(self):
        """Commands are sorted alphabetically by file path."""
        proc = self._run("--list")
        # The db-backup.sh should come before docker/ and git/ files
        db_pos = proc.stdout.find("db-backup")
        docker_pos = proc.stdout.find("docker")
        git_pos = proc.stdout.find("git")
        # db-backup is at the root level, should appear before subdirs
        self.assertLess(db_pos, docker_pos)
        # docker/ sorts before git/
        self.assertLess(docker_pos, git_pos)

    # ── Non-interactive export mode ─────────────────────────────────────

    def test_exec_flag_exists(self):
        """--exec is a recognized flag (we can't interactively select,
        but the flag should parse without error)."""
        # Without a TTY, the finder will fail gracefully
        proc = subprocess.run(
            [*CMD_FIND, "-c", str(self.config_path), "--exec"],
            capture_output=True,
            text=True,
            env={**os.environ, "TERM": "dumb"},
        )
        # Should exit with 130 (SIGINT equivalent, user cancelled)
        # or 1 on error — either way, it shouldn't crash
        self.assertIn(proc.returncode, (0, 1, 130))


if __name__ == "__main__":
    unittest.main()
