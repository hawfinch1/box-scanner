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


if __name__ == "__main__":
    unittest.main()
