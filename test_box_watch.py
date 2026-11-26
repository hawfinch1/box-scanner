import unittest
import pandas as pd
import box
from box_watch import candidates
from test_history_cases import history


class WatchTests(unittest.TestCase):
    def query(self, values, active=None, provisional=None):
        df = history(values)
        listing = pd.DataFrame([dict(Key="A", Code="000001", Name="시험")])
        return candidates(active or {}, {"A": df}, listing,
                          box.BoxParams(min_days=4, max_days=4, min_touches=1, max_drift_ratio=1),
                          box.MAParams(periods=[]), 0, 1, df.index[-1].date(), 3, provisional)

    def test_keep_bounds_and_retire_on_close(self):
        values = [100, 102, 100, 102, 103]
        active, highs, _ = self.query(values)
        self.assertEqual(highs[0]["고정 상단"], 102)
        self.assertEqual(highs[0]["상태"], "상단 초과·확인 대기")
        ended, highs, lows = self.query(values + [106], active)
        self.assertFalse(highs or lows)
        self.assertEqual(self.query(values + [106], ended), (ended, [], []))

    def test_confirmed_recovery(self):
        values = [100, 102, 100, 102, 99]
        active, _, lows = self.query(values)
        self.assertEqual(lows[0]["상태"], "하단 미만·반등 관찰")
        values += [100.5]
        self.assertEqual(self.query(values, active)[2][0]["상태"], "하단 회복 확인")
        provisional = history(values).index[-1].date()
        self.assertEqual(self.query(values, active, provisional)[2][0]["종가"], 99)
