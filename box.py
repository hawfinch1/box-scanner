"""박스권 판별 로직과 데이터 수집 (국내: 코스피·코스닥, 미국: 나스닥)."""
from __future__ import annotations

import datetime as dt
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

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
    min_daily_vol_pct: float = 0.0  # 박스 구간 일간 등락률 표준편차 하한(%). 인수합병 대기처럼 가격이 고정된 종목 제외용


@dataclass
class MAParams:
    periods: list[int] = field(default_factory=lambda: [5, 20, 60])  # 사용할 이동평균선
    cluster: bool = False         # 이평선 밀집(수렴) 조건 사용 여부
    max_spread_pct: float = 3.0   # 선택한 이평선들의 최대-최소 차이 허용치(%)
    ref_period: int | None = None  # 현재가 위치를 따질 기준 이평선
    ref_side: str = "any"          # "above" | "below" | "any"


# ───────────────────────── 종목 목록 ─────────────────────────

_session = requests.Session()
_session.headers["User-Agent"] = "Mozilla/5.0"


def list_krx(markets: list[str]) -> pd.DataFrame:
    df = fdr.StockListing("KRX")
    df = df[df["Market"].isin(markets)].copy()
    # 우선주·스팩·ETN·리츠 제외
    df = df[~df["Name"].astype(str).str.contains("스팩|ETN|리츠", regex=True)]
    df = df[df["Code"].str[-1] == "0"]  # 보통주만(우선주 코드는 5,7,9 등으로 끝남)
    df["Key"] = df["Code"]
    return df[["Key", "Code", "Name", "Market"]].reset_index(drop=True)


def _nasdaq_page(page: int) -> list[dict]:
    r = _session.get(
        "https://api.stock.naver.com/stock/exchange/NASDAQ/marketValue",
        params={"page": page, "pageSize": 100}, timeout=10,
    )
    return r.json().get("stocks", [])


def list_nasdaq() -> pd.DataFrame:
    """네이버 해외주식에서 나스닥 상장 보통주 목록(시가총액순)을 가져온다."""
    first = _session.get(
        "https://api.stock.naver.com/stock/exchange/NASDAQ/marketValue",
        params={"page": 1, "pageSize": 100}, timeout=10,
    ).json()
    pages = (first.get("totalCount", 0) + 99) // 100
    stocks = list(first.get("stocks", []))
    with ThreadPoolExecutor(8) as ex:
        for s in ex.map(_nasdaq_page, range(2, pages + 1)):
            stocks.extend(s)
    rows = [
        {"Key": s["reutersCode"], "Code": s["symbolCode"], "Name": s.get("stockName") or s.get("stockNameEng"),
         "Market": "NASDAQ"}
        for s in stocks if s.get("stockEndType") == "stock" and s.get("reutersCode")
    ]
    return pd.DataFrame(rows).drop_duplicates("Key").reset_index(drop=True)


# ───────────────────────── 시세 ─────────────────────────

_ITEM = re.compile(r'data="(\d{8})\|(\d+)\|(\d+)\|(\d+)\|(\d+)\|(\d+)"')


def _finish(df: pd.DataFrame, days: int) -> pd.DataFrame | None:
    if df.empty:
        return None
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").astype(float).sort_index()
    df = df[df["Volume"] > 0]  # 거래정지일 제외
    return df.tail(days)


def fetch_krx(code: str, days: int) -> pd.DataFrame | None:
    """네이버 차트 데이터에서 국내 종목 일봉."""
    try:
        r = _session.get(
            "https://fchart.stock.naver.com/sise.nhn",
            params={"symbol": code, "timeframe": "day", "count": days + 10, "requestType": 0},
            timeout=10,
        )
        rows = _ITEM.findall(r.text)
    except Exception:
        return None
    return _finish(pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"]), days)


def fetch_us(key: str, days: int) -> pd.DataFrame | None:
    """네이버 해외주식 차트 데이터에서 미국 종목 일봉(key 예: AAPL.O)."""
    end = dt.datetime.now() + dt.timedelta(days=1)
    start = end - dt.timedelta(days=int(days * 1.5) + 20)
    try:
        r = _session.get(
            f"https://api.stock.naver.com/chart/foreign/item/{key}/day",
            params={"startDateTime": start.strftime("%Y%m%d0000"), "endDateTime": end.strftime("%Y%m%d0000")},
            timeout=10,
        )
        data = r.json()
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    df = pd.DataFrame(data).rename(columns={
        "localDate": "Date", "openPrice": "Open", "highPrice": "High", "lowPrice": "Low",
        "closePrice": "Close", "accumulatedTradingVolume": "Volume",
    })
    cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
    if not set(cols) <= set(df.columns):
        return None
    return _finish(df[cols].dropna(), days)


def fetch_many(keys: list[str], days: int, fetcher, workers: int = 16, progress=None) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetcher, k, days): k for k in keys}
        for i, f in enumerate(as_completed(futs), 1):
            df = f.result()
            if df is not None:
                out[futs[f]] = df
            if progress:
                progress(i, len(keys))
    return out


# ───────────────────────── 박스권 판별 ─────────────────────────

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
    last = float(close[-1])
    seg = df.iloc[-best["days"]:]
    best["close"] = last
    best["position_pct"] = (last - best["lower"]) / (best["upper"] - best["lower"]) * 100
    best["start"] = seg.index[0].date()
    best["avg_value"] = float((seg["Close"] * seg["Volume"]).mean())
    best["daily_vol"] = float(seg["Close"].pct_change().std() * 100)
    if p.min_daily_vol_pct and not best["daily_vol"] >= p.min_daily_vol_pct:
        return None
    return best


def ma_check(df: pd.DataFrame, m: MAParams) -> dict | None:
    """이동평균선 조건을 확인하고 지표를 돌려준다. 조건 불만족이면 None."""
    close = df["Close"]
    last = float(close.iloc[-1])
    out: dict = {}
    vals = []
    for n in m.periods:
        v = float(close.tail(n).mean()) if len(close) >= n else np.nan
        vals.append(v)
    vals_arr = np.array(vals, float)
    if len(m.periods) >= 2 and not np.isnan(vals_arr).any():
        out["ma_spread"] = (vals_arr.max() - vals_arr.min()) / vals_arr.min() * 100
    else:
        out["ma_spread"] = np.nan
    if m.cluster and (np.isnan(out["ma_spread"]) or out["ma_spread"] > m.max_spread_pct):
        return None
    if m.ref_period:
        if len(close) < m.ref_period:
            return None
        ref = float(close.tail(m.ref_period).mean())
        out["ref_gap"] = (last - ref) / ref * 100
        if m.ref_side == "above" and last < ref:
            return None
        if m.ref_side == "below" and last > ref:
            return None
    return out


def scan(histories: dict[str, pd.DataFrame], listing: pd.DataFrame, p: BoxParams, m: MAParams,
         min_value: float = 0.0, value_div: float = 1e8) -> pd.DataFrame:
    """min_value 단위: value_div 로 나눈 거래대금 (국내 1e8=억원, 미국 1e6=백만달러)."""
    info = listing.set_index("Key")
    rows = []
    for key, df in histories.items():
        if key not in info.index:
            continue
        r = detect_box(df, p)
        if not r or r["avg_value"] / value_div < min_value:
            continue
        mr = ma_check(df, m)
        if mr is None:
            continue
        rows.append({"Key": key, "종목코드": info.at[key, "Code"], "종목명": info.at[key, "Name"],
                     "시장": info.at[key, "Market"], **r, **mr, "avg_value": r["avg_value"] / value_div})
    if not rows:
        return pd.DataFrame()
    res = pd.DataFrame(rows).rename(columns={
        "days": "박스기간(일)", "start": "시작일", "close": "현재가", "upper": "상단", "lower": "하단",
        "width_pct": "박스폭(%)", "position_pct": "박스내위치(%)", "upper_touches": "상단터치",
        "lower_touches": "하단터치", "avg_value": "평균거래대금", "ma_spread": "이평밀집도(%)",
        "ref_gap": "기준이평 대비(%)", "daily_vol": "일변동성(%)",
    })
    return res.sort_values(["박스기간(일)", "박스폭(%)"], ascending=[False, True]).reset_index(drop=True)
