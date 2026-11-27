import unittest

import pandas as pd
from plotly.subplots import make_subplots

import box
from touch_markers import add_touch_markers, touch_points


class TouchMarkerTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame(
            {"Close": [100, 102, 109, 110, 105, 109, 109, 100],
             "High": [101, 103, 111, 112, 106, 111, 110, 101],
             "Low": [98, 100, 108, 109, 104, 108, 108, 98]},
            index=pd.bdate_range("2026-01-01", periods=8))

    def test_first_bar_and_inclusive_boundary(self):
        points = touch_points(self.frame, 110, 100, box.BoxParams())
        self.assertEqual([self.frame.index.get_loc(p["date"]) for p in points if p["side"] == "상단"], [2, 5])
        self.assertEqual([self.frame.index.get_loc(p["date"]) for p in points if p["side"] == "하단"], [0, 7])
        self.assertEqual([p["price"] for p in points if p["side"] == "상단"], [109, 109])

    def test_wick_basis_matches_engine_count(self):
        params = box.BoxParams(use_close=False, min_touches=1, max_drift_ratio=10, max_width_pct=30)
        upper, lower = self.frame.High.max(), self.frame.Low.min()
        points = touch_points(self.frame, upper, lower, params)
        result = box._check(self.frame.Close.to_numpy(), self.frame.High.to_numpy(),
                            self.frame.Low.to_numpy(), params)
        self.assertEqual(sum(p["side"] == "상단" for p in points), result["upper_touches"])
        self.assertEqual(sum(p["side"] == "하단" for p in points), result["lower_touches"])
        for p in points:
            self.assertEqual(p["price"], self.frame.at[p["date"], "High" if p["side"] == "상단" else "Low"])

    def test_dotted_vertical_lines_and_clipped_group(self):
        fig = make_subplots(rows=2, cols=1)
        points = add_touch_markers(fig, [(self.frame, 110, 100)], box.BoxParams(), self.frame.index[3:])
        self.assertNotIn(self.frame.index[3], [p["date"] for p in points])
        for line in (t for t in fig.data if t.mode == "lines"):
            self.assertEqual(line.line.dash, "dot")
            for i in range(0, len(line.x), 3):
                self.assertEqual(line.x[i], line.x[i + 1])
                self.assertIsNone(line.x[i + 2])
        for triangle in (t for t in fig.data if t.showlegend):
            matching = [p for p in points if p["side"] in triangle.name]
            self.assertEqual(list(triangle.x), [p["date"] for p in matching])
            self.assertEqual([d[0] for d in triangle.customdata], [p["price"] for p in matching])
