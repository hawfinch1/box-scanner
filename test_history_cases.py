import io
import unittest
import pandas as pd
import box
import history_cases
from history_cases import collect_cases, similar_cases


def history(closes):
    return pd.DataFrame({"Open": closes, "High": [x + 5 for x in closes],
                         "Low": [x - 5 for x in closes], "Close": closes, "Volume": 1000},
                        index=pd.bdate_range("2025-01-01", periods=len(closes)))


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.p = box.BoxParams(min_days=4, max_days=4, min_touches=1, max_drift_ratio=1)
        self.ma = box.MAParams(periods=[])

    def collect(self, values, **kwargs):
        return collect_cases({"TEST": history(values)}, self.p, self.ma, **kwargs)

    def test_equality_and_wicks_do_not_end_fixed_box(self):
        r = self.collect([100, 102, 100, 102, 102, 100, 103]).iloc[0]
        self.assertEqual(r["상단"], 102)
        self.assertEqual(r["하단"], 100)
        self.assertEqual(r["탐지후관찰봉수"], 3)
        self.assertEqual(r["방향"], "상방")

    def test_lower_exit(self):
        r = self.collect([100, 102, 100, 102, 99]).iloc[0]
        self.assertEqual(r["방향"], "하방")
        self.assertEqual(r["탐지후관찰봉수"], 1)

    def test_unfinished_and_zero_followup_retained(self):
        for tail, expected in [([], 0), ([101, 101], 2)]:
            r = self.collect([100, 102, 100, 102] + tail).iloc[0]
            self.assertFalse(r["종료여부"])
            self.assertIsNone(r["종료일"])
            self.assertEqual(r["탐지후관찰봉수"], expected)

    def test_no_duplicates_and_restart_only_after_exit(self):
        rows = self.collect([100, 102, 100, 102, 101, 103, 110, 112, 110, 112, 113])
        self.assertEqual(len(rows), 2)
        self.assertGreater(rows.iloc[1]["박스시작일"], rows.iloc[0]["종료일"])
        self.assertEqual(rows["사례ID"].nunique(), 2)

    def test_future_does_not_change_detection(self):
        base = [100, 102, 100, 102]
        a = self.collect(base + [103]).iloc[0]
        b = self.collect(base + [99]).iloc[0]
        for key in ["사례ID", "탐지일", "상단", "하단", "박스폭(%)", "탐지시박스기간"]:
            self.assertEqual(a[key], b[key])

    def test_provisional_exit_excluded(self):
        df = history([100, 102, 100, 102, 103])
        rows = collect_cases({"TEST": df}, self.p, self.ma, provisional_date=df.index[-1].date())
        self.assertFalse(rows.iloc[0]["종료여부"])

    def test_similarity_uses_detection_features(self):
        cases = self.collect([100, 102, 100, 102, 103])
        target = {"박스기간(일)": 4, "박스폭(%)": 2, "박스내위치(%)": 100}
        self.assertEqual(len(similar_cases(cases, target, 0, 0, 0)), 1)
        self.assertEqual(len(similar_cases(cases, {**target, "박스기간(일)": 30}, 0, 0, 0)), 0)


    def test_lower_equality_does_not_end(self):
        # 하단(100)과 같은 종가 두 번은 유지, 99에서 하방 종료(탐지 다음 봉부터 3번째)
        r = self.collect([100, 102, 100, 102, 100, 100, 99]).iloc[0]
        self.assertEqual(r["방향"], "하방")
        self.assertEqual(r["탐지후관찰봉수"], 3)
        self.assertEqual(r["종료종가"], 99)

    def test_wick_only_breach_does_not_end(self):
        df = history([100, 102, 100, 102, 101, 101])
        df.loc[df.index[4], "High"] = 150  # 장중 고가만 상단 크게 이탈
        df.loc[df.index[5], "Low"] = 50    # 장중 저가만 하단 크게 이탈
        r = collect_cases({"TEST": df}, self.p, self.ma).iloc[0]
        self.assertFalse(r["종료여부"])
        self.assertEqual(r["탐지후관찰봉수"], 2)

    def test_listing_columns_and_leading_zero_csv(self):
        listing = pd.DataFrame([{"Key": "005930", "Code": "005930", "Name": "삼성전자", "Market": "KOSPI"}])
        rows = collect_cases({"005930": history([100, 102, 100, 102, 103])}, self.p, self.ma, listing=listing)
        r = rows.iloc[0]
        self.assertEqual((r["종목코드"], r["종목명"], r["시장"]), ("005930", "삼성전자", "KOSPI"))
        self.assertEqual(str(r["시세시작일"]), "2025-01-01")
        raw_csv = history_cases.to_csv_bytes(rows).decode("utf-8-sig")
        excel_csv = history_cases.to_csv_bytes(rows, excel=True).decode("utf-8-sig")
        self.assertIn(",005930,", raw_csv)
        self.assertIn('"=""005930"""', excel_csv)
        back = pd.read_csv(io.StringIO(raw_csv), dtype={"종목코드": str})
        self.assertEqual(back.loc[0, "종목코드"], "005930")

    def test_bad_stock_skipped_with_errors_list(self):
        bad = history([100, 102, 100, 102, 103])
        bad.loc[bad.index[2], "Close"] = float("nan")
        errs = []
        rows = collect_cases({"BAD": bad, "OK": history([100, 102, 100, 102, 103])},
                             self.p, self.ma, errors=errs)
        self.assertEqual(set(rows["Key"]), {"OK"})
        self.assertEqual(errs[0][0], "BAD")

    def test_missing_days_against_calendar(self):
        df = history([100, 102, 100, 102, 101, 101, 103])
        cal = df.index
        gapped = df.drop(df.index[5])  # 탐지 후 하루 시세 없음(거래정지 등)
        r = collect_cases({"T": gapped}, self.p, self.ma, calendar=cal).iloc[0]
        self.assertEqual(r["탐지후관찰봉수"], 2)       # 관측 봉수
        self.assertEqual(r["탐지후달력거래일수"], 3)   # 실제 거래일
        self.assertEqual(r["탐지후누락일수"], 1)

    def test_current_case_and_similar_use_detection_features(self):
        cases = collect_cases({
            "A": history([100, 102, 100, 102, 103]),      # 과거 종료 사례
            "B": history([100, 102, 100, 102, 101, 101]),  # 지금 이어지는 사례
        }, self.p, self.ma)
        last = history([0] * 6).index[-1].date()
        target = history_cases.current_case(cases, "B", last)
        self.assertIsNotNone(target)
        self.assertFalse(target["종료여부"])
        self.assertIsNone(history_cases.current_case(cases, "A", last))
        sim = similar_cases(cases, target, 0, 0, 0, before=last)
        self.assertNotIn(target["사례ID"], set(sim["사례ID"]))  # 자기 자신 제외
        self.assertEqual(set(sim["Key"]), {"A"})


class BreakoutV2Tests(unittest.TestCase):
    """돌파 규칙 v2: 상방 종가 ≥ U×(1+b), 하방 종가 ≤ L×(1−b), 그 사이는 추적 유지."""

    def setUp(self):
        self.p = box.BoxParams(min_days=4, max_days=4, min_touches=1, max_drift_ratio=1)
        self.ma = box.MAParams(periods=[])

    def collect(self, values, b=3.0, df=None):
        df = history(values) if df is None else df
        return collect_cases({"T": df}, self.p, self.ma, rule="v2", band_pct=b)

    # 박스: 100~102 → U=102, L=100. b=3% → 상방 기준 105.06, 하방 기준 97
    def test_close_equal_to_threshold_is_breakout(self):
        r = self.collect([100, 102, 100, 102, 101, 102 * 1.03]).iloc[0]
        self.assertEqual(r["방향"], "상방")
        self.assertEqual(r["탐지후관찰봉수"], 2)
        r = self.collect([100, 102, 100, 102, 97]).iloc[0]
        self.assertEqual(r["방향"], "하방")
        self.assertEqual(r["탐지후관찰봉수"], 1)

    def test_between_box_and_threshold_keeps_tracking(self):
        # 103·105(상단 초과지만 105.06 미만)와 98(하단 미만이지만 97 초과)은 돌파 아님
        r = self.collect([100, 102, 100, 102, 103, 105, 98, 99]).iloc[0]
        self.assertFalse(r["종료여부"])
        self.assertEqual(r["방향"], "관찰 중")
        self.assertEqual(r["탐지후관찰봉수"], 4)
        # v1 규칙이라면 103에서 바로 종료됐을 사례
        v1 = collect_cases({"T": history([100, 102, 100, 102, 103, 105, 98, 99])}, self.p, self.ma).iloc[0]
        self.assertEqual((v1["방향"], v1["탐지후관찰봉수"]), ("상방", 1))

    def test_wick_beyond_threshold_is_not_breakout(self):
        df = history([100, 102, 100, 102, 101, 101])
        df.loc[df.index[4], "High"] = 200
        df.loc[df.index[5], "Low"] = 10
        r = self.collect(None, df=df).iloc[0]
        self.assertFalse(r["종료여부"])

    def test_first_direction_recorded(self):
        # 하방 기준 먼저(97), 그 뒤 상방 기준(110) → 하방, 첫 돌파일 기록
        rows = self.collect([100, 102, 100, 102, 101, 96, 110])
        r = rows.iloc[0]
        self.assertEqual(r["방향"], "하방")
        self.assertEqual(r["탐지후관찰봉수"], 2)
        self.assertEqual(r["종료일"], history([0] * 7).index[5].date())
        self.assertEqual(r["종료종가"], 96)

    def test_thresholds_fixed_and_recorded(self):
        r = self.collect([100, 102, 100, 102, 101, 104, 103, 106]).iloc[0]
        self.assertAlmostEqual(r["상방기준가"], 102 * 1.03)
        self.assertAlmostEqual(r["하방기준가"], 100 * 0.97)
        self.assertEqual((r["상단"], r["하단"]), (102, 100))  # 추적 중 경계 불변
        self.assertEqual((r["방향"], r["탐지후관찰봉수"]), ("상방", 4))

    def test_rule_versions_do_not_mix(self):
        vals = [100, 102, 100, 102, 104]
        v1 = collect_cases({"T": history(vals)}, self.p, self.ma).iloc[0]
        b3 = self.collect(vals, 3.0).iloc[0]
        b2 = self.collect(vals, 2.0).iloc[0]
        self.assertEqual(v1["규칙버전"], "fixed-close-v1")
        self.assertEqual(b3["규칙버전"], "fixed-close-b-v2(b=3%)")
        self.assertEqual(b2["규칙버전"], "fixed-close-b-v2(b=2%)")
        self.assertEqual(len({v1["사례ID"], b3["사례ID"], b2["사례ID"]}), 3)
        # b가 바뀌면 결과도 달라짐: 104는 b=2%(104.04) 미달·b=3% 미달 → 둘 다 관찰 중, v1은 상방
        self.assertEqual(v1["방향"], "상방")
        self.assertEqual((b2["방향"], b3["방향"]), ("관찰 중", "관찰 중"))
        self.assertEqual(self.collect([100, 102, 100, 102, 104.1], 2.0).iloc[0]["방향"], "상방")
        self.assertEqual(self.collect([100, 102, 100, 102, 104.1], 3.0).iloc[0]["방향"], "관찰 중")

    def test_future_does_not_change_detection_v2(self):
        base = [100, 102, 100, 102]
        a = self.collect(base + [110]).iloc[0]
        b = self.collect(base + [90]).iloc[0]
        for key in ["사례ID", "탐지일", "상단", "하단", "상방기준가", "하방기준가", "탐지시박스기간"]:
            self.assertEqual(a[key], b[key])

    def test_provisional_bar_not_used_v2(self):
        df = history([100, 102, 100, 102, 120])
        r = collect_cases({"T": df}, self.p, self.ma, rule="v2", band_pct=3.0,
                          provisional_date=df.index[-1].date()).iloc[0]
        self.assertFalse(r["종료여부"])

    def test_restart_after_breakout_no_overlap_v2(self):
        rows = self.collect([100, 102, 100, 102, 106, 110, 112, 110, 112, 116])
        self.assertEqual(len(rows), 2)
        self.assertGreater(rows.iloc[1]["박스시작일"], rows.iloc[0]["종료일"])

    def test_invalid_band_rejected(self):
        with self.assertRaises(ValueError):
            self.collect([100, 102, 100, 102], b=0)


if __name__ == "__main__":
    unittest.main()
