# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest import batch_metrics, bootstrap_ci, evaluate_ticket, permutation_p_value  # noqa: E402
from config import GAME_MAP  # noqa: E402
from models import Draw  # noqa: E402


class EvaluateTicketTests(unittest.TestCase):
    def test_ssq_top(self):
        g = GAME_MAP["ssq"]
        draw = Draw("ssq", "1", "2026-01-01", [1, 2, 3, 4, 5, 6], [7])
        r = evaluate_ticket(g, [1, 2, 3, 4, 5, 6], [7], draw)
        self.assertEqual(r.main_hits, 6)
        self.assertEqual(r.extra_hits, 1)
        self.assertTrue(r.top_hit)
        self.assertTrue(r.high_hit)
        self.assertAlmostEqual(r.match_fraction, 1.0)

    def test_ssq_partial(self):
        g = GAME_MAP["ssq"]
        draw = Draw("ssq", "1", "2026-01-01", [1, 2, 3, 4, 5, 6], [7])
        r = evaluate_ticket(g, [1, 2, 3, 10, 11, 12], [8], draw)
        self.assertEqual(r.main_hits, 3)
        self.assertFalse(r.high_hit)
        self.assertFalse(r.top_hit)

    def test_dlt_top(self):
        g = GAME_MAP["dlt"]
        draw = Draw("dlt", "1", "2026-01-01", [1, 2, 3, 4, 5], [1, 2])
        r = evaluate_ticket(g, [1, 2, 3, 4, 5], [1, 2], draw)
        self.assertTrue(r.top_hit)

    def test_digit_near(self):
        g = GAME_MAP["fc3d"]
        draw = Draw("fc3d", "1", "2026-01-01", [1, 2, 4], [])
        r = evaluate_ticket(g, [1, 2, 3], [], draw)
        self.assertEqual(r.main_hits, 2)
        self.assertTrue(r.high_hit)
        self.assertFalse(r.top_hit)

    def test_keno_top(self):
        g = GAME_MAP["kl8"]
        draw = Draw("kl8", "1", "2026-01-01", list(range(1, 21)), [])
        r = evaluate_ticket(g, list(range(1, 11)), [], draw)
        self.assertEqual(r.main_hits, 10)
        self.assertTrue(r.top_hit)
        self.assertTrue(r.high_hit)

    def test_batch_metrics(self):
        g = GAME_MAP["ssq"]
        draw = Draw("ssq", "1", "2026-01-01", [1, 2, 3, 4, 5, 6], [7])
        m = batch_metrics(g, [([1, 2, 3, 4, 5, 6], [7]), ([8, 9, 10, 11, 12, 13], [1])], draw)
        self.assertEqual(m["tickets"], 2)
        self.assertEqual(m["high_hits"], 1)
        self.assertEqual(m["top_hits"], 1)


class StatsTests(unittest.TestCase):
    def test_zero_diffs(self):
        self.assertEqual(bootstrap_ci([0.0, 0.0, 0.0]), (0.0, 0.0))
        self.assertEqual(permutation_p_value([0.0, 0.0, 0.0]), 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
