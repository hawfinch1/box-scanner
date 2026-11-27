import datetime as dt
import hashlib
import json
import os
import pickle
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

import box
from test_history_cases import history

APP = Path(__file__).with_name("app.py")


def session_at(timestamp):
    return box.provisional_date("kr", dt.datetime.fromisoformat(timestamp))


class DomesticCloseTests(unittest.TestCase):
    def test_session_boundary(self):
        for timestamp, expected in [
            ("2026-11-26T18:30", "2026-11-26"),
            ("2026-11-27T08:59", "2026-11-26"),
            ("2026-11-27T09:00", "2026-11-27"),
            ("2026-11-28T12:00", "2026-11-27"),
            ("2026-03-02T18:30", "2026-02-27"),  # 월요일 대체공휴일
            ("2026-03-03T08:59", "2026-02-27"),
            ("2026-03-03T09:00", "2026-03-03"),
        ]:
            with self.subTest(timestamp=timestamp):
                self.assertEqual(str(session_at(timestamp + "+09:00")), expected)

    def test_recent_button_refetches_and_reclassifies(self):
        st.cache_data.clear()
        keys = ["up_lost", "down_lost", "up_new", "down_new"]
        listing = pd.DataFrame(dict(Key=keys, Name=keys, Code=keys, Market="KOSPI"))

        def quotes(closes):
            frames = {}
            for key, close in zip(keys, closes):
                df = history([100, 102] * 40 + [close])
                df.index = pd.bdate_range(end="2026-11-26", periods=len(df))
                df["Volume"] = 20_000_000
                frames[key] = df
            return frames

        provisional = quotes([108, 95, 101, 101])
        final = quotes([101, 101, 108, 95])
        before = session_at("2026-11-27T08:59+09:00")
        after = session_at("2026-11-27T09:00+09:00")
        with patch.object(box, "provisional_date", return_value=before) as clock, \
             patch.object(box, "list_krx", return_value=listing), \
             patch.object(box, "fetch_many", side_effect=[provisional, final]) as fetch:
            app = AppTest.from_file(str(APP), default_timeout=60).run()
            for _ in range(2):
                app.button(key="recent_run").click().run()
                self.assertFalse(app.exception)
                rows, date, *_ = app.session_state["recent_view"]
                self.assertEqual((rows, str(date)), ([], "2026-11-25"))
            self.assertEqual(fetch.call_count, 1)
            clock.return_value = after
            app.button(key="recent_run").click().run()
            self.assertFalse(app.exception)
            rows, date, *_ = app.session_state["recent_view"]
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(str(date), "2026-11-26")
            self.assertEqual({(r["종목코드"], r["방향"]) for r in rows},
                             {("up_new", "상방"), ("down_new", "하방")})
            # 새 기준일에 재조회가 실패하면 이전 표가 렌더링되지 않는다.
            clock.return_value = dt.date(2026, 11, 30)
            fetch.side_effect = OSError("test offline")
            app.button(key="recent_run").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.warning)
            self.assertFalse(app.dataframe)
        st.cache_data.clear()

    @unittest.skipUnless(os.getenv("BOX_REVIEW_DIR"), "로컬 검증 자료 지정 시 실행")
    def test_review_snapshot_through_recent_button(self):
        folder = Path(os.environ["BOX_REVIEW_DIR"])
        config = json.loads((folder / "results/run_config.json").read_text(encoding="utf-8-sig"))
        cache = folder / "cache/kr_raw.pkl"
        with cache.open("rb") as stream:
            self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), config["cache_sha256"])
            stream.seek(0)
            listing, raw, fetched_at = pickle.load(stream)
        session = session_at(fetched_at)
        expected_table = pd.read_csv(folder / "results/recent_modes_cases.csv", dtype={"종목코드": str})
        expected = expected_table[(expected_table["날짜"] == config["asof"]) & expected_table["방식A 포함"]]
        st.cache_data.clear()
        with patch.object(box, "provisional_date", return_value=session), \
             patch.object(box, "list_krx", return_value=listing), \
             patch.object(box, "fetch_many", return_value=raw):
            app = AppTest.from_file(str(APP), default_timeout=120).run()
            app.button(key="recent_run").click().run()
            self.assertFalse(app.exception)
            rows, date, *_ = app.session_state["recent_view"]
            self.assertEqual(str(date), config["asof"])
            self.assertEqual(sorted((r["종목코드"], r["방향"]) for r in rows),
                             sorted(zip(expected["종목코드"], expected["방향"])))
        st.cache_data.clear()

