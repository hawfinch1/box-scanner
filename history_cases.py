"""검색 당시 고정한 경계에 대한 과거 사례 수집. 미래 값은 탐지에 사용하지 않는다."""
from dataclasses import asdict
import hashlib
import json

import pandas as pd

import box

RULE_VERSION = "fixed-close-v1"  # 종가가 상단 초과/하단 미만이면 종료
RULE_V2 = "fixed-close-b-v2"      # 종가가 상단×(1+b%) 이상/하단×(1−b%) 이하이면 돌파
CODE_COLUMNS = ["종목코드", "Key"]
_EPS = 1e-12  # 부동소수점 오차로 기준가와 같은 종가가 갈리지 않도록 하는 상대 허용치


def rule_version(rule="v1", band_pct=None):
    """사례에 기록할 규칙 버전 문자열. v2는 돌파폭을 함께 기록해 b가 다른 사례와 섞이지 않게 한다."""
    if rule == "v1":
        return RULE_VERSION
    if rule == "v2":
        if band_pct is None or band_pct <= 0:
            raise ValueError("v2 규칙에는 0보다 큰 돌파폭(band_pct)이 필요합니다.")
        return f"{RULE_V2}(b={band_pct:g}%)"
    raise ValueError(f"알 수 없는 규칙: {rule}")


def _thresholds(upper, lower, rule, band_pct):
    """(상방 기준가, 하방 기준가, 상방 판정 함수, 하방 판정 함수)"""
    if rule == "v1":
        return upper, lower, (lambda c: c > upper), (lambda c: c < lower)
    up = upper * (1 + band_pct / 100)
    dn = lower * (1 - band_pct / 100)
    return up, dn, (lambda c: c >= up * (1 - _EPS)), (lambda c: c <= dn * (1 + _EPS))


def collect_cases(histories, p, ma, min_value=0.0, value_div=1e8,
                  provisional_date=None, progress=None, listing=None,
                  calendar=None, collected_at=None, errors=None, rule="v1", band_pct=None):
    """종목별 과거 사례를 비중첩 방식으로 수집한다.

    listing: Key·Code·Name·Market 열이 있는 종목 목록(있으면 종목코드·종목명·시장 기록)
    calendar: 거래일 달력(있으면 탐지 후 누락일 수 기록)
    errors: 리스트를 넘기면 시세 오류 종목을 건너뛰고 (Key, 사유)를 담는다. 없으면 예외를 낸다.
    rule: "v1"(경계 초과/미만 종료) 또는 "v2"(돌파폭 band_pct% 적용, 기준가 이상/이하면 돌파)
    """
    version = rule_version(rule, band_pct)
    rows = []
    settings = json.dumps({"box": asdict(p), "ma": asdict(ma),
                           "min_value": min_value, "value_div": value_div},
                          sort_keys=True, ensure_ascii=False)
    info = listing.set_index("Key") if listing is not None and not listing.empty else None
    cal = pd.DatetimeIndex(calendar) if calendar is not None else None
    for number, (key, raw) in enumerate(histories.items(), 1):
        try:
            df = _clean(key, raw, provisional_date)
        except ValueError as exc:
            if errors is None:
                raise
            errors.append((key, str(exc)))
            if progress:
                progress(number, len(histories))
            continue
        if info is not None and key in info.index:
            code, name, market = info.at[key, "Code"], info.at[key, "Name"], info.at[key, "Market"]
        else:
            code, name, market = key, key, ""
        data_start = df.index[0].date() if len(df) else None
        data_end = df.index[-1].date() if len(df) else None
        # 한 사례를 추적하는 동안 재탐지하지 않는다. 종료 후 새 구간부터 탐지.
        floor = 0
        i = p.min_days - 1
        while i < len(df):
            r = box.detect_box(df.iloc[floor:i + 1], p)
            prefix = df.iloc[:i + 1]
            if (r is None or r["avg_value"] / value_div < min_value
                    or box.ma_check(prefix, ma) is None):
                i += 1
                continue
            future = df.iloc[i + 1:]
            up_px, dn_px, is_up, is_dn = _thresholds(r["upper"], r["lower"], rule, band_pct)
            fc = future.Close
            crossed = is_up(fc) | is_dn(fc)
            ended = bool(crossed.any())
            remaining = int(crossed.to_numpy().argmax()) + 1 if ended else len(future)
            end_i = i + remaining
            end_close = float(df.Close.iloc[end_i])
            direction = ("상방" if is_up(end_close) else "하방") if ended else "관찰 중"
            obs_end = df.index[end_i]
            if cal is not None:
                window = cal[(cal > df.index[i]) & (cal <= obs_end)]
                cal_days = int(len(window))
                missing = int(len(window.difference(df.index)))
            else:
                cal_days = missing = None
            # v1 사례ID는 이전과 같게 유지(재현성), v2는 규칙 버전(돌파폭 포함)을 ID에 넣는다
            identity = (f"{key}|{df.index[i].isoformat()}|{settings}" if rule == "v1"
                        else f"{key}|{df.index[i].isoformat()}|{settings}|{version}")
            rows.append({
                "사례ID": hashlib.sha256(identity.encode()).hexdigest()[:20],
                "Key": key, "종목코드": code, "종목명": name, "시장": market,
                "탐지일": df.index[i].date(), "박스시작일": r["start"],
                "탐지시박스기간": r["days"], "상단": r["upper"], "하단": r["lower"],
                "돌파폭(%)": band_pct if rule == "v2" else 0.0,
                "상방기준가": up_px, "하방기준가": dn_px,
                "박스폭(%)": r["width_pct"], "탐지시위치(%)": r["position_pct"],
                "일변동성(%)": r["daily_vol"], "상단터치": r["upper_touches"],
                "하단터치": r["lower_touches"], "평균거래대금": r["avg_value"] / value_div,
                "종료여부": ended, "방향": direction,
                "종료일": obs_end.date() if ended else None,
                "관찰종료일": obs_end.date(),
                "탐지후관찰봉수": remaining,
                "탐지후달력거래일수": cal_days,
                "탐지후누락일수": missing,
                "종료종가": end_close if ended else None,
                "시세시작일": data_start, "시세마지막일": data_end,
                "수집시각": collected_at,
                "규칙버전": version, "검색조건JSON": settings,
            })
            if not ended:
                break
            floor = end_i + 1
            i = floor + p.min_days - 1
        if progress:
            progress(number, len(histories))
    return pd.DataFrame(rows)


def _clean(key, raw, provisional_date):
    df = raw.sort_index().copy()
    if df.index.has_duplicates:
        raise ValueError(f"{key}: 중복 날짜가 있습니다.")
    if provisional_date is not None:
        df = df[df.index.date != provisional_date]
    required = ["Open", "High", "Low", "Close", "Volume"]
    if df[required].isna().any().any() or not (df[required] > 0).all().all():
        raise ValueError(f"{key}: 누락 또는 0 이하 시세가 있습니다.")
    return df


def current_case(cases, key, as_of):
    """해당 종목에서 as_of(분석 기준일)까지 이어지는 관찰 중 사례. 없으면 None.
    현재 스캐너 결과(오늘 기준 최장 박스)와 비교 기준을 맞추기 위해 쓴다."""
    if cases is None or cases.empty:
        return None
    m = (cases["Key"] == key) & (~cases["종료여부"].astype(bool))
    m &= pd.to_datetime(cases["관찰종료일"]) == pd.Timestamp(as_of)
    hit = cases[m]
    return None if hit.empty else hit.iloc[-1]


def similar_cases(cases, target, days_tolerance=10, width_tolerance=3.0,
                  position_tolerance=25.0, before=None):
    """탐지 당시 특징을 비교한다. 현재 결과를 보고 유사도를 바꾸지 않는다.

    target 이 과거 사례 행(탐지시박스기간 등)이면 같은 정의의 값끼리 비교하고
    자기 자신(같은 사례ID)은 뺀다. 스캔 결과 행이면 그 값을 그대로 쓴다."""
    if cases.empty:
        return cases.copy()
    if "탐지시박스기간" in target:
        days, width, pos = target["탐지시박스기간"], target["박스폭(%)"], target["탐지시위치(%)"]
    else:
        days, width, pos = target["박스기간(일)"], target["박스폭(%)"], target["박스내위치(%)"]
    mask = (cases["탐지시박스기간"] - days).abs() <= days_tolerance
    mask &= (cases["박스폭(%)"] - width).abs() <= width_tolerance
    mask &= (cases["탐지시위치(%)"] - pos).abs() <= position_tolerance
    if before is not None:
        mask &= pd.to_datetime(cases["탐지일"]) < pd.Timestamp(before)
    if "사례ID" in target:
        mask &= cases["사례ID"] != target["사례ID"]
    return cases[mask].copy()


def to_csv_bytes(df, excel=False):
    """CSV 바이트. excel=True면 종목코드를 ="005930" 형태로 감싸 엑셀에서도 앞자리 0이 남게 한다.
    (원본 CSV는 값 그대로 저장되며 파일 안에서는 앞자리 0이 보존된다.)"""
    out = df.copy()
    if excel:
        for c in CODE_COLUMNS:
            if c in out.columns:
                out[c] = out[c].map(lambda v: f'="{v}"')
    return out.to_csv(index=False).encode("utf-8-sig")
