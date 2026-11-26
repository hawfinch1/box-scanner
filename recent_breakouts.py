"""직전 박스 대비 최신 확정 종가 이탈 검색."""
import box
from history_cases import _thresholds


def latest_breakouts(histories, listing, params, ma, min_value, value_div, previous, latest, band):
    names = listing.set_index("Key")
    rows = []
    for key, df in histories.items():
        if len(df) < params.min_days + 1 or tuple(df.index[-2:]) != (previous, latest):
            continue
        before = df.iloc[:-1]
        close = df.Close.iloc[-1]
        # 직전 종가는 반드시 직전 박스 안에 있으므로 작은 등락은 미리 제외 가능.
        _, _, possible_up, possible_down = _thresholds(before.Close.iloc[-1], before.Close.iloc[-1], "v2", band)
        if not (possible_up(close) or possible_down(close)):
            continue
        case = box.detect_box(before, params)
        if not case or case["avg_value"] < min_value * value_div or box.ma_check(before, ma) is None:
            continue
        upper, lower = case["upper"], case["lower"]
        _, _, up, down = _thresholds(upper, lower, "v2", band)
        if up(close) or down(close):
            boundary = upper if up(close) else lower
            rows.append({"종목명": names.at[key,"Name"], "종목코드": names.at[key,"Code"],
                         "방향": "상방" if up(close) else "하방", "돌파일": latest.date(),
                         "직전 박스기간": case["days"], "상단": upper, "하단": lower,
                         "확정 종가": close, "경계 대비(%)": round((close/boundary-1)*100, 2)})
    return sorted(rows, key=lambda row: abs(row["경계 대비(%)"]), reverse=True)
