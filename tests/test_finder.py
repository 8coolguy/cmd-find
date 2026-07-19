"""Tests for cmd_find.finder — fuzzy matching algorithm."""

import unittest

from cmd_find.finder import _fuzzy_match


class TestFuzzyMatch(unittest.TestCase):
    """Test the _fuzzy_match scoring function."""

    # ── Exact and prefix matches ────────────────────────────────────────

    def test_exact_match(self):
        """Exact match scores higher than partial."""
        score = _fuzzy_match("git rebase", "git rebase")
        self.assertGreater(score, 0)

    def test_prefix_match_gets_bonus(self):
        """Matching from position 0 gets a prefix bonus."""
        score_prefix = _fuzzy_match("git", "git checkout branch")
        score_mid = _fuzzy_match("git", "some git command")
        self.assertGreater(score_prefix, score_mid)

    def test_consecutive_gets_bonus(self):
        """Consecutive character matches score higher."""
        score_cons = _fuzzy_match("abc", "abc")
        score_gap = _fuzzy_match("abc", "axbxc")
        self.assertGreater(score_cons, score_gap)

    # ── No match ────────────────────────────────────────────────────────

    def test_no_match_returns_negative(self):
        """Characters not found in text → negative score."""
        score = _fuzzy_match("xyz", "abc")
        self.assertLess(score, 0)

    def test_partial_match_returns_negative(self):
        """Not all query chars found → negative score."""
        score = _fuzzy_match("gitx", "git rebase")
        self.assertLess(score, 0)

    # ── Empty query ─────────────────────────────────────────────────────

    def test_empty_query_returns_zero(self):
        """Empty query matches everything with score 0."""
        self.assertEqual(_fuzzy_match("", "anything"), 0.0)
        self.assertEqual(_fuzzy_match("", ""), 0.0)

    # ── Case insensitivity ──────────────────────────────────────────────

    def test_case_insensitive(self):
        """Matching is case-insensitive."""
        lower = _fuzzy_match("docker", "Docker cleanup command")
        upper = _fuzzy_match("DOCKER", "docker cleanup command")
        mixed = _fuzzy_match("DoCkEr", "DOCKER cleanup")
        self.assertGreater(lower, 0)
        self.assertGreater(upper, 0)
        self.assertGreater(mixed, 0)
        # All three should score the same
        self.assertEqual(lower, upper)
        self.assertEqual(upper, mixed)

    # ── Scoring order (better match > worse match) ──────────────────────

    def test_better_match_scores_higher(self):
        """A tighter match scores higher than a looser one."""
        score_tight = _fuzzy_match("dckr", "docker")
        score_loose = _fuzzy_match("dckr", "d o c k e r x")
        self.assertGreater(score_tight, score_loose)

    def test_shorter_distance_scores_higher(self):
        """Match with smaller gaps between chars scores higher."""
        score1 = _fuzzy_match("abc", "abc def")
        score2 = _fuzzy_match("abc", "a b c d e f")
        self.assertGreater(score1, score2)

    # ── Real-world style queries ────────────────────────────────────────

    def test_real_world_queries(self):
        """Queries that resemble actual usage."""
        # "grb" should match "git rebase"
        self.assertGreater(_fuzzy_match("grb", "git rebase"), 0)
        # "dclean" should match "docker cleanup"
        self.assertGreater(
            _fuzzy_match("dclean", "docker cleanup all containers"), 0
        )
        # "undo" should match "undo the last commit"
        self.assertGreater(
            _fuzzy_match("undo", "undo the last commit keeping changes"), 0
        )


if __name__ == "__main__":
    unittest.main()
