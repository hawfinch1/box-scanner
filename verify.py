"""박스 판별 검증 스크립트.

1) 앱의 판별(box.detect_box)과 독립적으로 짠 단순 구현(순수 파이썬 반복문)을 전 종목에 돌려 결과를 비교
2) 네이버 시세를 다른 출처(국내: FinanceDataReader/KRX, 미국: Yahoo Finance)와 대조

실행: .venv\\Scripts\\python verify.py
"""
import random
import sys

import pandas as pd

import box


def naive_box(closes, highs, lows, p: box.BoxParams):
    """box._check/detect_box 를 보지 않고 설명문대로 다시 짠 구현."""
    best = None
    n_all = len(closes)
    for n in range(p.min_days, min(p.max_days, n_all) + 1):
        c = closes[-n:]
        h = c if p.use_close else highs[-n:]
        l = c if p.use_close else lows[-n:]
        top, bot = max(h), min(l)
        if bot <= 0 or top == bot:
            continue
        if (top - bot) / bot * 100 > p.max_width_pct:
            continue
        # 최소제곱 직선의 기울기
        xm = (n - 1) / 2
        ym = sum(c) / n
        slope = sum((i - xm) * (y - ym) for i, y in enumerate(c)) / sum((i - xm) ** 2 for i in range(n))
        if abs(slope * (n - 1)) > (top - bot) * p.max_drift_ratio + 1e-9:
            continue
        zone = (top - bot) * p.touch_zone
        def touches(flags):
            cnt, prev = 0, False
            for f in flags:
                if f and not prev:
                    cnt += 1
                prev = f
            return cnt
        if touches([x >= top - zone for x in h]) < p.min_touches:
            continue
        if touches([x <= bot + zone for x in l]) < p.min_touches:
            continue
        best = (n, top, bot)
    return best


def compare_logic(histories, p, label):
    mismatch = []
    found = 0
    for k, df in histories.items():
        a = box.detect_box(df, box.BoxParams(**{**p.__dict__, "min_daily_vol_pct": 0.0}))
        b = naive_box(df["Close"].tolist(), df["High"].tolist(), df["Low"].tolist(), p)
        a_t = (a["days"], round(a["upper"], 6), round(a["lower"], 6)) if a else None
        b_t = (b[0], round(b[1], 6), round(b[2], 6)) if b else None
        found += a_t is not None
        if a_t != b_t:
            mismatch.append((k, a_t, b_t))
    print(f"[{label}] {p.use_close and '종가' or '고저가'} 기준: 종목 {len(histories):,} · 박스 검출 {found:,} · 불일치 {len(mismatch)}")
    for m in mismatch[:5]:
        print("   불일치:", m)
    return not mismatch


def compare_source_kr(histories, n=15):
    import FinanceDataReader as fdr
    keys = random.sample(list(histories), n)
    worst = 0.0
    for k in keys:
        a = histories[k]["Close"].tail(60)
        b = fdr.DataReader(k, str(a.index[0].date()))["Close"]
        j = pd.concat([a, b], axis=1, join="inner").dropna()
        d = ((j.iloc[:, 0] - j.iloc[:, 1]).abs() / j.iloc[:, 1] * 100).max()
        worst = max(worst, d)
        print(f"   {k}: 겹친 {len(j)}일, 최대 차이 {d:.3f}%")
    print(f"[국내 시세 대조] 네이버 vs FinanceDataReader {n}종목 최근 60일 종가 최대 차이 {worst:.3f}%")


def compare_source_us(histories, n=15):
    import yfinance as yf
    keys = random.sample(list(histories), n)
    syms = {k: k.split(".")[0] for k in keys}
    ydf = yf.download(list(syms.values()), period="6mo", auto_adjust=False, progress=False, group_by="ticker")
    worst = 0.0
    for k, s in syms.items():
        a = histories[k]["Close"].tail(60)
        try:
            b = ydf[s]["Close"]
        except KeyError:
            print(f"   {s}: 야후 데이터 없음")
            continue
        j = pd.concat([a, b], axis=1, join="inner").dropna()
        if j.empty:
            print(f"   {s}: 겹치는 날짜 없음")
            continue
        d = ((j.iloc[:, 0] - j.iloc[:, 1]).abs() / j.iloc[:, 1] * 100).max()
        worst = max(worst, d)
        print(f"   {s}: 겹친 {len(j)}일, 최대 차이 {d:.3f}%")
    print(f"[미국 시세 대조] 네이버 vs Yahoo {n}종목 최근 60일 종가 최대 차이 {worst:.3f}%")


if __name__ == "__main__":
    random.seed(7)
    ok = True
    lk = box.list_krx(["KOSPI", "KOSDAQ", "KOSDAQ GLOBAL"])
    hk = box.fetch_many(lk["Key"].tolist(), 250, box.fetch_krx)
    lu = box.list_nasdaq()
    hu = box.fetch_many(lu["Key"].tolist(), 250, box.fetch_us)
    for use_close in (True, False):
        p = box.BoxParams(min_days=10, max_days=60, use_close=use_close)
        ok &= compare_logic(hk, p, "국내")
        ok &= compare_logic(hu, p, "미국")
    compare_source_kr(hk)
    compare_source_us(hu)
    sys.exit(0 if ok else 1)
