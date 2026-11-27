import unittest

import numpy as np

from indicators import indicators
from test_history_cases import history


class AlignmentTests(unittest.TestCase):
    def test_first_day_and_maintenance(self):
        values = [100] * 60 + [101]
        self.assertEqual(indicators(history(values))["골든크로스"], "오늘 완성")
        self.assertEqual(indicators(history(values + [102]))["골든크로스"], "유지")
        self.assertEqual(indicators(history([100] * 61))["골든크로스"], "미충족")

    def test_five_must_be_above_twenty(self):
        values = [100] * 40 + [110] * 15 + [105] * 6
        self.assertGreater(np.mean(values[-5:]), np.mean(values[-60:]))
        self.assertLess(np.mean(values[-5:]), np.mean(values[-20:]))
        self.assertEqual(indicators(history(values))["골든크로스"], "미충족")

    def test_120_requires_complete_order_and_yesterday(self):
        values = [100] * 120 + [101]
        self.assertEqual(indicators(history(values), include_120=True)["골든크로스"], "오늘 완성")
        self.assertEqual(indicators(history(values + [102]), include_120=True)["골든크로스"], "유지")
        self.assertEqual(indicators(history(values[:120]), include_120=True)["골든크로스"], "자료 부족")
        values = [120] * 60 + [100] * 60 + [101]
        self.assertEqual(indicators(history(values))["골든크로스"], "오늘 완성")
        self.assertEqual(indicators(history(values), include_120=True)["골든크로스"], "미충족")

    def test_reverse_order_first_day_and_maintenance(self):
        values = [100] * 120 + [99]
        self.assertEqual(indicators(history(values), include_120=True)["데드크로스"], "오늘 완성")
        self.assertEqual(indicators(history(values + [98]), include_120=True)["데드크로스"], "유지")
