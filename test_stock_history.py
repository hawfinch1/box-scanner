import unittest

import pandas as pd

from stock_history import visible_boxes


class HistoryWindowTests(unittest.TestCase):
    def test_clipped_closed_and_open_intervals(self):
        dates = pd.bdate_range("2026-06-01", periods=8)
        bars = pd.DataFrame({"Close": [10, 11, 12, 13, 15, 20, 21, 20]}, index=dates)
        cases = pd.DataFrame([
            {"박스시작일": dates[0], "탐지일": dates[2], "관찰종료일": dates[4],
             "종료일": dates[4], "종료여부": True, "방향": "상방", "하단": 10, "상단": 12},
            {"박스시작일": dates[5], "탐지일": dates[7], "관찰종료일": dates[7],
             "종료일": None, "종료여부": False, "방향": "관찰 중", "하단": 20, "상단": 21},
        ])
        result = list(visible_boxes(cases, bars, bars.iloc[2:]))
        self.assertEqual([list(index) for index, _ in result], [list(dates[2:4]), list(dates[5:])])
        self.assertEqual([r["전체 구간(봉)"] for _, r in result], [4, 3])
        self.assertEqual([r["표시 기간 내 박스 안 종가(봉)"] for _, r in result], [1, 3])
