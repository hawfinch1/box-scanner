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


if __name__ == "__main__":
    unittest.main()
