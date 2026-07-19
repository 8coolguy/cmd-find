"""Tests for cmd_find.config — TOML loading, path expansion, defaults, mode."""

import os
import tempfile
import unittest
from pathlib import Path

from cmd_find.config import Config, create_default_config, load_config


class TestConfigLoading(unittest.TestCase):
    """Tests for load_config()."""

    def test_no_config_file_returns_default(self):
        """When no config file exists, return default Config."""
        nonexistent = Path("/tmp/cmd-find-nonexistent-12345.toml")
        config = load_config(nonexistent)
        self.assertEqual(config.directories, [])
        self.assertEqual(config.mode, "print")

    def test_loads_directory_list(self):
        """A valid config file returns the listed directories."""
        cfg = tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        )
        cfg.write('directories = ["/tmp/foo", "/tmp/bar"]\n')
        cfg.close()

        try:
            config = load_config(Path(cfg.name))
            self.assertEqual(len(config.directories), 2)
            self.assertEqual(config.directories[0], Path("/tmp/foo").resolve())
            self.assertEqual(config.directories[1], Path("/tmp/bar").resolve())
        finally:
            os.unlink(cfg.name)

    def test_expands_tilde(self):
        """~ is expanded to the user's home directory."""
        cfg = tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        )
        cfg.write('directories = ["~/my-commands"]\n')
        cfg.close()

        try:
            config = load_config(Path(cfg.name))
            self.assertEqual(len(config.directories), 1)
            self.assertEqual(config.directories[0], Path.home() / "my-commands")
        finally:
            os.unlink(cfg.name)

    def test_expands_env_vars(self):
        """$ENV_VAR is expanded."""
        os.environ["CMD_FIND_TEST_DIR"] = "/tmp/env-test-dir"
        cfg = tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        )
        cfg.write('directories = ["$CMD_FIND_TEST_DIR/sub"]\n')
        cfg.close()

        try:
            config = load_config(Path(cfg.name))
            self.assertEqual(len(config.directories), 1)
            self.assertEqual(
                config.directories[0], Path("/tmp/env-test-dir/sub").resolve()
            )
        finally:
            os.unlink(cfg.name)
            del os.environ["CMD_FIND_TEST_DIR"]

    def test_deduplicates_directories(self):
        """Duplicate paths are removed, preserving first-occurrence order."""
        cfg = tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        )
        cfg.write(
            'directories = ["/tmp/a", "/tmp/b", "/tmp/a", "/tmp/c", "/tmp/b"]\n'
        )
        cfg.close()

        try:
            config = load_config(Path(cfg.name))
            self.assertEqual(len(config.directories), 3)
            self.assertEqual(config.directories[0], Path("/tmp/a").resolve())
            self.assertEqual(config.directories[1], Path("/tmp/b").resolve())
            self.assertEqual(config.directories[2], Path("/tmp/c").resolve())
        finally:
            os.unlink(cfg.name)

    def test_empty_directories_list(self):
        """An empty directories list returns empty."""
        cfg = tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        )
        cfg.write('directories = []\n')
        cfg.close()

        try:
            config = load_config(Path(cfg.name))
            self.assertEqual(config.directories, [])
        finally:
            os.unlink(cfg.name)

    def test_default_mode_is_print(self):
        """When no mode is set, default to 'print'."""
        cfg = tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        )
        cfg.write('directories = ["/tmp/x"]\n')
        cfg.close()

        try:
            config = load_config(Path(cfg.name))
            self.assertEqual(config.mode, "print")
        finally:
            os.unlink(cfg.name)

    def test_reads_mode(self):
        """The mode field is read from config."""
        cfg = tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        )
        cfg.write('directories = ["/tmp/x"]\nmode = "copy"\n')
        cfg.close()

        try:
            config = load_config(Path(cfg.name))
            self.assertEqual(config.mode, "copy")
        finally:
            os.unlink(cfg.name)

    def test_invalid_mode_falls_back_to_print(self):
        """An unrecognized mode value falls back to 'print'."""
        cfg = tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        )
        cfg.write('directories = ["/tmp/x"]\nmode = "garbage"\n')
        cfg.close()

        try:
            config = load_config(Path(cfg.name))
            self.assertEqual(config.mode, "print")
        finally:
            os.unlink(cfg.name)

    def test_exec_mode(self):
        """mode = 'exec' is valid."""
        cfg = tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        )
        cfg.write('directories = ["/tmp/x"]\nmode = "exec"\n')
        cfg.close()

        try:
            config = load_config(Path(cfg.name))
            self.assertEqual(config.mode, "exec")
        finally:
            os.unlink(cfg.name)


class TestCreateDefaultConfig(unittest.TestCase):
    """Tests for create_default_config()."""

    def test_creates_config_with_mode_comment(self):
        """create_default_config creates config with mode documentation."""
        tmp_base = Path(tempfile.mkdtemp())
        config_path = tmp_base / "config.toml"
        try:
            result = create_default_config(config_path)
            self.assertTrue(config_path.exists())
            self.assertEqual(result, config_path)

            config = load_config(config_path)
            self.assertEqual(len(config.directories), 1)
            self.assertEqual(config.mode, "print")
        finally:
            import shutil
            shutil.rmtree(tmp_base, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
