"""최근 확정 봉으로 박스를 등록하고 같은 세션에서 최초 경계를 추적한다."""
import pandas as pd
import box
from history_cases import _thresholds


def candidates(tracked, histories, listing, p, ma, min_value, value_div, as_of, band, provisional):
    frames = {k: df.loc[df.index.date <= as_of] for k, df in histories.items()}
    if provisional is not None:
        frames = {k: df.loc[df.index.date != provisional] for k, df in frames.items()}
    frames = {k: df for k, df in frames.items() if len(df)}
    if not frames:
        return dict(tracked), [], []
    latest = max(df.index[-1] for df in frames.values())
    names = listing.set_index("Key")
    active = dict(tracked)
    upper_rows, lower_rows = [], []
    for key, df in frames.items():
        if df.index[-1] != latest:
            continue
        case = active.get(key)
        if case and case[1] is None:
            # 종료일 이후 봉만 모아 새 박스 탐지를 시작한다.
            df = df.loc[df.index > case[0]]
            if len(df) < p.min_days:
                continue
            case = None
        if case and case[0] < df.index[0]:
            # 이전 탐지일부터 시세가 남아 있지 않으면 연속 추적을 보장할 수 없다.
            active.pop(key)
            case = None
        if case is None:
            # 첫 방문에도 어제의 박스와 오늘의 움직임을 비교할 수 있게 한다.
            for window in (df.iloc[:-1], df):
                r = box.detect_box(window, p)
                if r and r["avg_value"] >= min_value * value_div and box.ma_check(window, ma) is not None:
                    case = (window.index[-1], float(r["upper"]), float(r["lower"]))
                    active[key] = case
                    break
        if case is None:
            continue
        detected, top, bottom = case
        up, down, crossed_up, crossed_down = _thresholds(top, bottom, "v2", band)
        subsequent = df.loc[df.index > detected, "Close"]
        crossed = crossed_up(subsequent) | crossed_down(subsequent)
        if crossed.any():
            # 같은 날 재검색해도 같은 깨진 박스를 재등록하지 않는다.
            active[key] = (subsequent.index[crossed][0], None, None)
            continue
        close = float(df.Close.iloc[-1])
        mid = (top + bottom) / 2
        width = top - bottom
        common = {"종목명": names.at[key,"Name"], "종목코드": names.at[key,"Code"],
                  "박스 등록일": detected.date(), "기준일": latest.date(), "종가": close,
                  "고정 상단": top, "고정 하단": bottom}
        if close >= top - width * .2:
            upper_rows.append({**common, "상태": "상단 초과·확인 대기" if close > top else "상단 접근",
                               "상방 확인선": up, "확인선까지(%)": (up/close-1)*100})
        previous = float(df.Close.iloc[-2]) if len(df)>1 else close
        recovered = detected < latest and previous <= bottom and close > bottom and close < mid
        if recovered or close <= bottom + width * .2:
            label = "하단 회복 확인" if recovered else ("하단 미만·반등 관찰" if close < bottom else "하단 접근")
            lower_rows.append({**common, "상태": label, "박스 중앙": mid,
                               "중앙까지 거리(%)": (mid/close-1)*100})
    return active, upper_rows, lower_rows
