# -*- coding: utf-8 -*-
"""核心逻辑回归测试。运行：python -m unittest discover -s tests -v"""
from __future__ import annotations

import math
import sys
import unittest
from datetime import date, datetime
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import GAME_MAP, GAMES, PROBABILITY_NOTES  # noqa: E402
from db import Database  # noqa: E402
from models import Draw, NextDraw  # noqa: E402
from recommend import build_recommendations  # noqa: E402
import recommend_features as F  # noqa: E402
from lottery_calendar import (
    latest_expected_draw_date, next_draw_date, resolve_next_draw,
)
from market_holidays import is_market_closed  # noqa: E402
from run_daily import next_issue  # noqa: E402


class ProbabilityTests(unittest.TestCase):
    def test_total_combinations(self):
        self.assertEqual(comb(33, 6) * 16, 17_721_088)
        self.assertEqual(comb(35, 5) * comb(12, 2), 21_425_712)
        self.assertEqual(comb(30, 7), 2_035_800)
        self.assertEqual(comb(80, 10), 1_646_492_110_120)
        self.assertEqual(10 ** 6 * 15, 15_000_000)

    def test_second_prize_counts(self):
        ssq_total = comb(33, 6) * 16
        self.assertAlmostEqual(ssq_total / 15, 1_181_405.87, places=2)
        dlt_total = comb(35, 5) * comb(12, 2)
        self.assertAlmostEqual(dlt_total / 20, 1_071_285.60, places=2)
        qlc_total = comb(30, 7)
        self.assertAlmostEqual(qlc_total / 7, 290_828.57, places=2)

    def test_keno_probabilities(self):
        total = comb(80, 10)
        top = comb(20, 10) / total
        nine = comb(20, 9) * comb(60, 1) / total
        self.assertAlmostEqual(1 / top, 8_911_711.18, places=2)
        self.assertAlmostEqual(1 / nine, 163_381.37, places=2)

    def test_notes_match_math(self):
        self.assertIn("1/1,181,406", PROBABILITY_NOTES["ssq"]["second"])
        self.assertIn("1/1,071,286", PROBABILITY_NOTES["dlt"]["second"])
        self.assertIn("1/290,829", PROBABILITY_NOTES["qlc"]["second"])
        self.assertIn("1/8,911,711", PROBABILITY_NOTES["kl8"]["top"])
        self.assertIn("1/163,381", PROBABILITY_NOTES["kl8"]["second"])


class FeatureTests(unittest.TestCase):
    def test_entropy(self):
        self.assertAlmostEqual(F.entropy([1, 1, 1]), 1.0, places=6)
        self.assertAlmostEqual(F.entropy([3, 0, 0]), 0.0, places=6)
        self.assertAlmostEqual(F.entropy([3, 3, 0]), math.log(2) / math.log(3), places=6)

    def test_percentile(self):
        self.assertAlmostEqual(F.percentile([1, 2, 3, 4], 0.5), 2.5, places=6)
        self.assertAlmostEqual(F.percentile([1], 0.9), 1.0, places=6)

    def test_digit_average_gaps(self):
        draws = [
            Draw("fc3d", "1", "2026-01-01", [0, 0, 0]),
            Draw("fc3d", "2", "2026-01-02", [1, 0, 0]),
            Draw("fc3d", "3", "2026-01-03", [0, 0, 0]),
            Draw("fc3d", "4", "2026-01-04", [1, 0, 0]),
        ]
        gaps = F.digit_average_gaps(draws, 0, 10)
        self.assertAlmostEqual(gaps[0], 2.0, places=6)
        self.assertAlmostEqual(gaps[1], 2.0, places=6)
        self.assertAlmostEqual(gaps[2], 10.0, places=6)


class NextIssueTests(unittest.TestCase):
    def test_regular(self):
        self.assertEqual(next_issue("2026127", "2026-11-05", "ssq"), "2026128")
        self.assertEqual(next_issue("26127", "2026-11-07", "dlt"), "26128")

    def test_december_daily_not_rolled_early(self):
        # 12 月 1 日仍然是本年，不能直接跳到下一年
        self.assertEqual(next_issue("2026335", "2026-12-01", "fc3d"), "2026336")
        self.assertEqual(next_issue("2026335", "2026-12-01", "kl8"), "2026336")

    def test_year_rollover(self):
        self.assertEqual(next_issue("26156", "2026-12-30", "dlt"), "27001")
        self.assertEqual(next_issue("26156", "2026-12-31", "qxc"), "27001")
        self.assertEqual(next_issue("2026151", "2026-12-31", "ssq"), "2027001")
        self.assertEqual(next_issue("2026365", "2026-12-31", "fc3d"), "2027001")
        self.assertEqual(next_issue("26365", "2026-12-31", "pl3"), "27001")


class NextDrawResolutionTests(unittest.TestCase):
    def test_official_next_draw_wins(self):
        official = NextDraw("dlt", "26128", "2026-11-09", "sporttery_official")
        issue, draw_date, source = resolve_next_draw(
            "dlt", "26127", "2026-11-07", official
        )
        self.assertEqual(issue, "26128")
        self.assertEqual(draw_date, "2026-11-09")
        self.assertEqual(source, "sporttery_official")

    def test_stale_official_falls_back_to_schedule(self):
        official = NextDraw("dlt", "26127", "2026-11-07", "sporttery_official")
        issue, draw_date, source = resolve_next_draw(
            "dlt", "26127", "2026-11-07", official
        )
        self.assertEqual(issue, "26128")
        self.assertEqual(draw_date, "2026-11-09")
        self.assertEqual(source, "schedule_official")


class MarketCalendarTests(unittest.TestCase):
    def test_2026_spring_festival_is_skipped(self):
        self.assertTrue(is_market_closed(date(2026, 2, 14)))
        self.assertEqual(next_draw_date("2026-02-12", "ssq").isoformat(), "2026-02-24")
        self.assertEqual(next_draw_date("2026-02-11", "dlt").isoformat(), "2026-02-25")
        self.assertEqual(next_draw_date("2026-02-13", "qlc").isoformat(), "2026-02-25")
        self.assertEqual(next_draw_date("2026-02-13", "qxc").isoformat(), "2026-02-24")
        self.assertEqual(next_draw_date("2026-02-13", "fc3d").isoformat(), "2026-02-24")

    def test_2027_provisional_calendar(self):
        self.assertEqual(next_draw_date("2027-02-03", "fc3d").isoformat(), "2027-02-14")
        self.assertEqual(next_draw_date("2027-02-03", "dlt").isoformat(), "2027-02-15")
        self.assertEqual(next_draw_date("2027-09-30", "fc3d").isoformat(), "2027-10-05")
        issue, draw_date, source = resolve_next_draw("fc3d", "2027034", "2027-02-03")
        self.assertEqual((issue, draw_date, source),
                         ("2027035", "2027-02-14", "schedule_provisional"))

    def test_expected_draw_date_respects_publish_cutoff(self):
        self.assertEqual(
            latest_expected_draw_date("fc3d", datetime.fromisoformat("2026-02-14T22:30:00")).isoformat(),
            "2026-02-13",
        )
        self.assertEqual(
            latest_expected_draw_date("fc3d", datetime.fromisoformat("2026-02-24T08:00:00")).isoformat(),
            "2026-02-13",
        )
        self.assertEqual(
            latest_expected_draw_date("fc3d", datetime.fromisoformat("2026-02-24T22:30:00")).isoformat(),
            "2026-02-24",
        )


class RecommendationBoundsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = Database(ROOT / "data" / "lottery.db")
        cls.db.init()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_all_games(self):
        for g in GAMES:
            with self.subTest(game=g.key):
                draws = self.db.get_draws(g.key)
                self.assertGreater(len(draws), 30, f"{g.name} 历史数据不足")
                latest = draws[-1]
                target = next_issue(latest.issue, latest.draw_date, g.key)
                sets = build_recommendations(g, draws, target, salt="selftest")
                self.assertEqual(len(sets), 5, f"{g.name} 未生成 5 组")

                for s in sets:
                    if g.kind == "lotto":
                        self.assertEqual(len(s.numbers), g.pick)
                        self.assertEqual(len(set(s.numbers)), g.pick)
                        self.assertTrue(all(1 <= n <= g.pool for n in s.numbers))
                        if g.extra_pick:
                            self.assertEqual(len(s.extra), g.extra_pick)
                            self.assertTrue(all(1 <= n <= g.extra_pool for n in s.extra))
                        if g.pool > 31:
                            self.assertTrue(any(n > 31 for n in s.numbers))
                    elif g.kind == "digit":
                        self.assertEqual(len(s.numbers), g.digits)
                        self.assertTrue(all(0 <= n <= 9 for n in s.numbers))
                        if g.back_pool:
                            self.assertEqual(len(s.extra), 1)
                            self.assertTrue(0 <= s.extra[0] < g.back_pool)
                    elif g.kind == "keno":
                        self.assertEqual(len(s.numbers), 10)
                        self.assertEqual(len(set(s.numbers)), 10)
                        self.assertTrue(all(1 <= n <= 80 for n in s.numbers))


if __name__ == "__main__":
    unittest.main(verbosity=2)
