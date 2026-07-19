"""Test runner for cmd-find test suite.

Usage:
    python -m tests.run              # discover and run all tests
    python -m tests.run --verbose    # verbose output
"""

import sys
import unittest

if __name__ == "__main__":
    # Discover all tests in the tests/ directory
    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir="tests",
        pattern="test_*.py",
        top_level_dir=".",
    )
    verbosity = 2 if "--verbose" in sys.argv else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
