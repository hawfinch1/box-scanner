import unittest

import pandas as pd

import outcomes


def cases(rows):
    """rows: (Key, 종료여부, 방향, 탐지후관찰봉수)"""
    return pd.DataFrame(rows, columns=["Key", "종료여부", "방향", "탐지후관찰봉수"])


class ClassifyTests(unittest.TestCase):
    def test_detection_day_basis(self):
        c = cases([
            ("A", True, "상방", 3),      # 5일 안 상방
            ("B", True, "하방", 7),      # 5일엔 미돌파, 10일엔 하방
            ("C", False, "관찰 중", 25),  # 20일까지 관측, 돌파 없음 → 미돌파
            ("D", False, "관찰 중", 4),   # 돌파 없이 4봉만 관측 → 5일 데이터부족
            ("E", True, "상방", 15),     # 관측이 짧았어도 돌파 확인 → 판정 가능
        ])
        r = outcomes.classify(c, age=0).set_index("Key")
        self.assertEqual(list(r["결과5"]), ["상방", "미돌파", "미돌파", "데이터부족", "미돌파"])
        self.assertEqual(list(r["결과10"]), ["상방", "하방", "미돌파", "데이터부족", "미돌파"])
        self.assertEqual(list(r["결과20"]), ["상방", "하방", "미돌파", "데이터부족", "상방"])

    def test_age_conditioning(self):
        # 현재 종목이 탐지 후 5봉째 미돌파 → 과거 사례도 5봉까지 미돌파인 것만, 그 뒤 h봉
        c = cases([
            ("A", True, "상방", 3),      # 5봉 전에 돌파 → 제외
            ("B", True, "상방", 5),      # 5봉째 돌파 → 제외(현재 종목은 5봉까지 미돌파)
            ("C", True, "하방", 8),      # 남은 3봉째 하방 → 5일 하방
            ("D", False, "관찰 중", 5),   # 5봉까지만 관측 → 포함, 5일 데이터부족
            ("E", False, "관찰 중", 12),  # 5+5=10까지 관측 → 5일 미돌파, 10일 데이터부족
        ])
        r = outcomes.classify(c, age=5).set_index("Key")
        self.assertEqual(sorted(r.index), ["C", "D", "E"])
        self.assertEqual(list(r["결과5"]), ["하방", "데이터부족", "미돌파"])
        self.assertEqual(list(r["결과10"]), ["하방", "데이터부족", "데이터부족"])


class SummarizeTests(unittest.TestCase):
    def test_cumulative_periods_keep_nonbreakouts_in_denominator(self):
        c = cases([("A", True, "상방", 7), ("B", True, "하방", 12),
                   ("C", False, "관찰 중", 25), ("D", False, "관찰 중", 6)])
        classified = outcomes.classify(c)
        result = [outcomes.summarize(classified, h, n_boot=20) for h in (5, 10, 20)]
        self.assertEqual([r["n"] for r in result], [4, 3, 3])
        self.assertEqual([r["counts"]["미돌파"] for r in result], [4, 2, 1])
        self.assertEqual([r["counts"]["데이터부족"] for r in result], [0, 1, 1])
        self.assertEqual(result[2]["counts"]["상방"], 1)
        self.assertEqual(result[2]["counts"]["하방"], 1)
        for r in result:
            self.assertAlmostEqual(sum(r["pct"].values()), 100)
            self.assertFalse(r["estimable"])

    def test_denominator_excludes_insufficient_and_sums_to_100(self):
        c = cases([("A", True, "상방", 2), ("B", True, "하방", 2), ("C", False, "관찰 중", 30),
                   ("D", False, "관찰 중", 1)])
        s = outcomes.summarize(outcomes.classify(c), 5, n_boot=200)
        self.assertEqual(s["n"], 3)
        self.assertEqual(s["counts"]["데이터부족"], 1)
        self.assertAlmostEqual(sum(s["pct"].values()), 100.0)
        self.assertAlmostEqual(s["pct"]["상방"], 100 / 3)
        self.assertFalse(s["estimable"])  # 3건 → 기준 미달

    def test_estimable_threshold_and_interval(self):
        rows = [(f"S{i % 12}", True, "상방" if i % 3 else "하방", 2) for i in range(36)]
        s = outcomes.summarize(outcomes.classify(cases(rows)), 5, n_boot=300)
        self.assertTrue(s["estimable"])  # 36건 · 12종목
        lo, hi = s["ci"]["상방"]
        self.assertLessEqual(lo, s["pct"]["상방"])
        self.assertGreaterEqual(hi, s["pct"]["상방"])
        few_stocks = [(f"S{i % 5}", True, "상방", 2) for i in range(40)]
        self.assertFalse(outcomes.summarize(outcomes.classify(cases(few_stocks)), 5, n_boot=50)["estimable"])

    def test_empty(self):
        s = outcomes.summarize(outcomes.classify(cases([])), 10)
        self.assertEqual(s["n"], 0)
        self.assertFalse(s["estimable"])


class BreakoutTimingTests(unittest.TestCase):
    def test_remaining_days_and_horizon_boundaries(self):
        c = cases([
            ("early", True, "상방", 3),
            ("at_age", True, "상방", 5),
            ("up", True, "상방", 6),
            ("down", True, "하방", 10),
            ("late", True, "상방", 11),
            ("open", False, "관찰 중", 15),
            ("short", False, "관찰 중", 7),
            ("too_short", False, "관찰 중", 4),
        ])
        original = c.copy(deep=True)
        t = outcomes.breakout_timing(c, age=5, h=5, min_n=1, min_stocks=1)
        self.assertEqual(t["n"], 2)
        self.assertEqual(t["mean"], 3.0)  # 1 and 5 extra bars, not 6 and 10
        self.assertEqual(t["median"], 3.0)
        self.assertEqual(t["counts"], {"상방": 1, "하방": 1, "미돌파": 2, "데이터부족": 1})
        self.assertEqual(t["by_direction"]["상방"]["mean"], 1.0)
        self.assertEqual(t["by_direction"]["하방"]["mean"], 5.0)
        pd.testing.assert_frame_equal(c, original)

    def test_no_breakout_is_not_zero_days(self):
        t = outcomes.breakout_timing(cases([("A", False, "관찰 중", 20)]), 0, 10)
        self.assertEqual(t["n"], 0)
        self.assertIsNone(t["mean"])
        self.assertIsNone(t["median"])
        self.assertFalse(t["estimable"])
        self.assertEqual(t["counts"]["미돌파"], 1)

    def test_empty(self):
        t = outcomes.breakout_timing(cases([]), 0, 20)
        self.assertEqual(t["n"], 0)
        self.assertIsNone(t["mean"])
        self.assertEqual(sum(t["counts"].values()), 0)

    def test_threshold_applies_to_completed_and_each_direction(self):
        c = cases([(f"S{i % 12}", True, "상방" if i % 2 else "하방", 3) for i in range(36)])
        t = outcomes.breakout_timing(c, 1, 5)
        self.assertTrue(t["estimable"])
        self.assertEqual(t["mean"], 2.0)
        self.assertFalse(t["by_direction"]["상방"]["estimable"])
        self.assertFalse(t["by_direction"]["하방"]["estimable"])

    def test_many_open_cases_do_not_make_mean_estimable(self):
        c = cases([(f"S{i}", False, "관찰 중", 20) for i in range(40)] + [("B", True, "상방", 2)])
        t = outcomes.breakout_timing(c, 0, 10)
        self.assertEqual(t["n"], 1)
        self.assertFalse(t["estimable"])

    def test_invalid_period(self):
        for age, h in [(-1, 5), (0, 0)]:
            with self.assertRaises(ValueError):
                outcomes.breakout_timing(cases([]), age, h)


if __name__ == "__main__":
    unittest.main()
