"""박스권 판별 로직과 데이터 수집."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import numpy as np
import pandas as pd
import requests
import FinanceDataReader as fdr


@dataclass
class BoxParams:
    min_days: int = 5          # 최소 박스 기간(거래일). 5거래일 = 1주
    max_days: int = 60         # 최대로 확인할 기간(거래일)
    max_width_pct: float = 10.0  # 박스 상단/하단 폭 허용치(%)
    max_drift_ratio: float = 0.5  # 추세(회귀선 변화폭)가 박스 폭의 몇 배까지 허용되는지
    min_touches: int = 2        # 상단·하단을 각각 최소 몇 번 건드려야 하는지
    touch_zone: float = 0.2     # 박스 높이의 몇 %를 터치 구간으로 볼지
    use_close: bool = True      # True: 종가 기준, False: 고가/저가(꼬리 포함) 기준


def list_stocks(markets: list[str]) -> pd.DataFrame:
    df = fdr.StockListing("KRX")
    df = df[df["Market"].isin(markets)].copy()
    # 우선주·스팩·ETN 등 노이즈 제외
    name = df["Name"].astype(str)
    df = df[~name.str.contains("스팩|ETN|리츠", regex=True)]
    df = df[df["Code"].str[-1] == "0"]  # 보통주만(우선주 코드는 5,7,9 등으로 끝남)
    return df[["Code", "Name", "Market"]].reset_index(drop=True)


_session = requests.Session()
_session.headers["User-Agent"] = "Mozilla/5.0"
_ITEM = re.compile(r'data="(\d{8})\|(\d+)\|(\d+)\|(\d+)\|(\d+)\|(\d+)"')


def fetch_history(code: str, days: int) -> pd.DataFrame | None:
    """네이버 차트 데이터에서 최근 일봉을 가져온다."""
    try:
        r = _session.get(
            "https://fchart.stock.naver.com/sise.nhn",
            params={"symbol": code, "timeframe": "day", "count": days + 10, "requestType": 0},
            timeout=10,
        )
        rows = _ITEM.findall(r.text)
    except Exception:
        return None
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").astype(float)
    df = df[df["Volume"] > 0]  # 거래정지일 제외
    return df.tail(days)


def fetch_many(codes: list[str], days: int, workers: int = 16, progress=None) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_history, c, days): c for c in codes}
        for i, f in enumerate(as_completed(futs), 1):
            df = f.result()
            if df is not None:
                out[futs[f]] = df
            if progress:
                progress(i, len(codes))
    return out


def _check(close: np.ndarray, hi: np.ndarray, lo: np.ndarray, p: BoxParams) -> dict | None:
    upper, lower = hi.max(), lo.min()
    if lower <= 0:
        return None
    height = upper - lower
    width_pct = height / lower * 100
    if width_pct > p.max_width_pct or height == 0:
        return None
    # 추세 확인: 회귀선이 기간 동안 움직인 폭이 박스 높이 대비 작아야 함
    n = len(close)
    slope = np.polyfit(np.arange(n), close, 1)[0]
    drift = abs(slope * (n - 1))
    if drift > height * p.max_drift_ratio:
        return None
    zone = height * p.touch_zone
    up_t = _count_touches(hi >= upper - zone)
    lo_t = _count_touches(lo <= lower + zone)
    if up_t < p.min_touches or lo_t < p.min_touches:
        return None
    return {
        "upper": upper,
        "lower": lower,
        "width_pct": width_pct,
        "upper_touches": up_t,
        "lower_touches": lo_t,
        "drift_ratio": drift / height,
    }


def _count_touches(mask: np.ndarray) -> int:
    """연속된 터치 구간은 1회로 셈."""
    m = mask.astype(int)
    return int(m[0] + np.sum((m[1:] == 1) & (m[:-1] == 0)))


def detect_box(df: pd.DataFrame, p: BoxParams) -> dict | None:
    """최근 시점에서 끝나는 가장 긴 박스 구간을 찾는다."""
    if len(df) < p.min_days:
        return None
    close = df["Close"].to_numpy(float)
    hi = close if p.use_close else df["High"].to_numpy(float)
    lo = close if p.use_close else df["Low"].to_numpy(float)
    best = None
    for n in range(p.min_days, min(p.max_days, len(df)) + 1):
        r = _check(close[-n:], hi[-n:], lo[-n:], p)
        if r:
            best = {**r, "days": n}
    if not best:
        return None
    last = float(df["Close"].iloc[-1])
    seg = df.iloc[-best["days"]:]
    best["close"] = last
    best["position_pct"] = (last - best["lower"]) / (best["upper"] - best["lower"]) * 100
    best["start"] = seg.index[0].date()
    best["avg_value_eok"] = float((seg["Close"] * seg["Volume"]).mean() / 1e8)
    return best


def scan(histories: dict[str, pd.DataFrame], listing: pd.DataFrame, p: BoxParams,
         min_value_eok: float = 0.0) -> pd.DataFrame:
    names = listing.set_index("Code")
    rows = []
    for code, df in histories.items():
        r = detect_box(df, p)
        if not r or r["avg_value_eok"] < min_value_eok:
            continue
        rows.append({"종목코드": code, "종목명": names.at[code, "Name"], "시장": names.at[code, "Market"], **r})
    if not rows:
        return pd.DataFrame()
    res = pd.DataFrame(rows).rename(columns={
        "days": "박스기간(일)", "start": "시작일", "close": "현재가", "upper": "상단", "lower": "하단",
        "width_pct": "박스폭(%)", "position_pct": "박스내위치(%)", "upper_touches": "상단터치",
        "lower_touches": "하단터치", "avg_value_eok": "평균거래대금(억)", "drift_ratio": "추세비율",
    })
    return res.sort_values(["박스기간(일)", "박스폭(%)"], ascending=[False, True]).reset_index(drop=True)
