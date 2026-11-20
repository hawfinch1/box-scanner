"""과거 사례의 기간별 돌파 결과(상방·하방·미돌파·데이터 부족)와 관측 비율 요약.

기준점: 현재 종목이 탐지 후 age봉 동안 돌파하지 않았다면, 과거 사례도 같은 age봉까지
돌파하지 않은 경우만 고르고 그 시점부터 h봉 안의 결과를 본다(age=0이면 탐지일 기준).
"""
import numpy as np
import pandas as pd

HORIZONS = (5, 10, 20)
MIN_N = 30        # 판정 가능한 사례 수 하한
MIN_STOCKS = 10   # 서로 다른 종목 수 하한
LABELS = ("상방", "하방", "미돌파", "데이터부족")


def classify(cases: pd.DataFrame, age: int = 0, horizons=HORIZONS) -> pd.DataFrame:
    """age봉까지 돌파하지 않은 사례만 남기고, 각 h에 대해 결과를 붙인다.

    필요한 열: 종료여부, 방향, 탐지후관찰봉수(돌파 사례는 돌파까지 봉수, 관찰 중은 관측 봉수)
    """
    if cases.empty:
        return cases.assign(**{f"결과{h}": pd.Series(dtype=object) for h in horizons})
    k = cases["탐지후관찰봉수"].astype(int)
    ended = cases["종료여부"].astype(bool)
    alive = (ended & (k > age)) | (~ended & (k >= age))
    out = cases[alive].copy()
    k, ended = k[alive], ended[alive]
    for h in horizons:
        lim = age + h
        res = np.where(ended & (k <= lim), out["방향"],                       # h봉 안에 돌파
              np.where((ended & (k > lim)) | (~ended & (k >= lim)), "미돌파",  # h봉까지 관측, 돌파 없음
                       "데이터부족"))                                        # 돌파 없이 관측이 h봉 미만
        out[f"결과{h}"] = res
    return out


def summarize(classified: pd.DataFrame, h: int, n_boot: int = 2000, seed: int = 0,
              min_n: int = MIN_N, min_stocks: int = MIN_STOCKS) -> dict:
    """h봉 결과의 건수·비율·95% 범위(종목 단위 부트스트랩).

    분모 = 상방 + 하방 + 미돌파(판정 가능 사례). 데이터 부족은 분모에서 빼고 따로 센다.
    """
    col = f"결과{h}"
    counts = {lab: int((classified[col] == lab).sum()) if len(classified) else 0 for lab in LABELS}
    decided = classified[classified[col].isin(LABELS[:3])] if len(classified) else classified
    n = len(decided)
    stocks = decided["Key"].nunique() if n else 0
    pct = {lab: (counts[lab] / n * 100 if n else np.nan) for lab in LABELS[:3]}
    ci = {lab: (np.nan, np.nan) for lab in LABELS[:3]}
    if n and stocks >= 2:
        rng = np.random.default_rng(seed)
        groups = [g[col].to_numpy() for _, g in decided.groupby("Key")]
        boots = {lab: [] for lab in LABELS[:3]}
        for _ in range(n_boot):
            pick = rng.integers(0, len(groups), len(groups))
            vals = np.concatenate([groups[i] for i in pick])
            for lab in LABELS[:3]:
                boots[lab].append((vals == lab).mean() * 100)
        ci = {lab: tuple(np.percentile(boots[lab], [2.5, 97.5])) for lab in LABELS[:3]}
    return {
        "h": h, "n": n, "stocks": stocks, "counts": counts, "pct": pct, "ci": ci,
        "estimable": n >= min_n and stocks >= min_stocks,
    }
