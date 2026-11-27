"""선택한 종목의 확정 일봉과 비중첩 박스 이력."""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import box
import history_cases
import mobile_ui
import related_etfs

GLOBAL_SEARCH_VERSION = 2


@st.cache_data(ttl=3600, show_spinner=False)
def symbols(region):
    return box.list_krx(["KOSPI", "KOSDAQ", "KOSDAQ GLOBAL"]) if region == "kr" else box.list_nasdaq()


@st.cache_data(ttl=1800, show_spinner=False)
def prices(region, key, epoch):
    fetch = box.fetch_krx if region == "kr" else box.fetch_us
    frame = fetch(key, 1500)
    if frame is None or frame.empty:
        raise ValueError("시세를 받지 못했습니다.")
    if epoch:
        frame = frame.loc[frame.index < pd.Timestamp(epoch)]
    if frame.empty:
        raise ValueError("확정 봉이 없습니다.")
    return frame


@st.cache_data(ttl=1800, show_spinner=False)
def collect(key, bars, params, ma, min_value, divisor, band):
    return history_cases.collect_cases({key: bars}, params, ma, min_value, divisor,
                                       rule="v2", band_pct=band)


def visible_boxes(cases, bars, shown):
    """표시 범위와 겹치는 구간만 집계한다. 돌파일은 박스 기간에서 제외한다."""
    for _, case in cases.iterrows():
        start = pd.Timestamp(case["박스시작일"])
        end = pd.Timestamp(case["관찰종료일"])
        period = bars.loc[start:end]
        if case["종료여부"]:
            period = period.loc[period.index < end]
        window = period.loc[shown.index[0]:shown.index[-1]]
        if window.empty:
            continue
        inside = window.Close.between(case["하단"], case["상단"]).sum()
        yield window.index, {
            "시작일": start.date(), "탐지일": case["탐지일"],
            "마지막 추적일(돌파 전)": period.index[-1].date(), "돌파일": case["종료일"],
            "상태": case["방향"], "전체 구간(봉)": len(period), "하단": case["하단"], "상단": case["상단"],
            "표시 기간 내 박스 안 종가(봉)": int(inside),
        }


def render(region, markets, params, ma, min_value, divisor, band):
    st.subheader("개별주 검색 · 과거 박스")
    frames = []
    for source, label in (("kr", "국내"), ("us", "미국·나스닥")):
        try:
            frame = symbols(source).copy()
            frame["Region"] = source
            frame["RegionLabel"] = label
            frames.append(frame)
        except Exception:
            st.warning(f"{label} 종목 목록을 받지 못했습니다. 다시 조회해 주세요.")
    if not frames:
        return
    listing = pd.concat(frames, ignore_index=True).drop_duplicates("Key").set_index("Key")
    st.caption("국내·미국 나스닥 통합 검색 · 애플 또는 AAPL, 테슬라 또는 TSLA로 검색 가능")
    key = st.selectbox("종목명 또는 코드 검색", listing.index, index=None, key="history_stock",
                       format_func=lambda k: f"{listing.at[k,'Name']} ({listing.at[k,'Code']}) · {listing.at[k,'RegionLabel']}")
    if key is None:
        return
    selected_region = listing.at[key, "Region"]
    if selected_region != region:
        min_value = 10.0 if selected_region == "kr" else 5.0
    region = selected_region
    divisor = 1e8 if region == "kr" else 1e6
    currency = "원" if region == "kr" else "USD"
    count = st.radio("표시할 최근 거래일", [120, 250, 500, 1250], index=2, horizontal=True,
                     format_func=lambda n: f"{n:,}일", key="history_count")
    chart_periods = st.multiselect("차트 이동평균선", [5, 10, 20, 60, 120, 240],
                                  default=[5, 20, 60, 120], key="history_chart_ma")

    try:
        epoch = box.provisional_date(region)
        full = prices(region, key, epoch)
        if epoch != box.provisional_date(region):
            st.info("확정 기준 시각이 바뀌었습니다. 다시 조회해 주세요.")
            return
    except ValueError as exc:
        st.warning(str(exc))
        return
    bars = full.tail(1250)
    shown = bars.tail(count)
    if st.checkbox("날짜로 구간 선택", key=f"history_dates_{region}_{key}"):
        selected = st.date_input(
            "확인할 시작일과 종료일", value=(shown.index[0].date(), shown.index[-1].date()),
            min_value=shown.index[0].date(), max_value=shown.index[-1].date(),
            key=f"history_range_{region}_{key}_{count}_{shown.index[-1].date()}")
        if len(selected) != 2:
            st.info("시작일과 종료일을 모두 선택해 주세요.")
            return
        shown = shown.loc[str(selected[0]):str(selected[1])]
        if shown.empty:
            st.info("선택한 날짜에 일봉이 없습니다. 거래일을 포함해 선택해 주세요.")
            return
    st.caption(f"{listing.at[key, 'Name']} ({listing.at[key, 'Code']}) · {shown.index[0]:%Y-%m-%d} ~ {shown.index[-1]:%Y-%m-%d} · 확정 일봉 · {currency}")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22])
    fig.add_trace(go.Candlestick(x=shown.index, open=shown.Open, high=shown.High, low=shown.Low,
                                 close=shown.Close, name="일봉"), row=1, col=1)
    colors = {5: "#f59f00", 10: "#37b24d", 20: "#e64980", 60: "#1c7ed6", 120: "#7048e8", 240: "#8d6e63"}
    for n in chart_periods:
        fig.add_trace(go.Scatter(x=shown.index, y=full.Close.rolling(n).mean().reindex(shown.index),
                                 name=f"{n}일선", line=dict(color=colors[n], width=1.5)), row=1, col=1)
    fig.add_trace(go.Bar(x=shown.index, y=shown.Volume, name="거래량"), row=2, col=1)
    records = []
    try:
        cases = collect(key, bars, params, ma, min_value, divisor, band)
    except ValueError as exc:
        st.warning(f"박스 이력 계산 불가 · {exc}")
        cases = None
    if cases is not None:
        for segment, record in visible_boxes(cases, bars, shown):
            records.append(record)
            fig.add_shape(type="rect", x0=segment[0], x1=segment[-1], y0=record["하단"],
                          y1=record["상단"], fillcolor="orange", opacity=0.2, line_width=1,
                          row=1, col=1)
    fig.update_layout(height=620, xaxis_rangeslider_visible=False)
    mobile_ui.render_chart(fig, f"{listing.at[key, 'Name']} · 과거 박스",
                           key=f"history_chart_{region}_{key}", currency="KRW" if region == "kr" else "USD")
    if any(full.Close.rolling(n).mean().reindex(shown.index).isna().any() for n in chart_periods):
        st.caption("상장 초기 등 이전 시세가 부족한 구간의 이동평균선은 계산 가능한 날부터 표시합니다.")
    if cases is not None:
        total = sum(r["표시 기간 내 박스 안 종가(봉)"] for r in records)
        st.write(f"현재 조건으로 탐지한 {len(records)}개 구간 · 관측 {len(shown)}봉 중 고정 경계 안 종가 {total}봉 ({total/len(shown):.1%})")
        st.caption(f"최대 1,250봉에서 겹치지 않는 박스를 탐지합니다. 음영은 형성 시작부터 돌파 전까지이며, 비율에는 고정 상·하단 안에서 마감한 날만 포함합니다. 종가 돌파 확인폭 {band:g}%.")
        st.caption(f"탐지 조건 · 최소 {params.min_days}봉 / 최대 {params.max_days}봉 · 박스 폭 {params.max_width_pct:g}% 이하 · 상하단 접촉 각각 {params.min_touches}회 · 가격 기준 {'종가' if params.use_close else '고가·저가'} · 최소 평균 거래대금 {min_value:g}{'억원' if region == 'kr' else '백만 USD'}")
        st.info("표시된 비율은 현재 조건과 최초 탐지 경계로 집계한 값입니다. 폭이 더 넓은 횡보나 돌파 후 새 박스를 형성하는 기간은 추가로 잡힐 수 있습니다. 왼쪽 검색 조건을 바꾸면 과거 이력도 다시 계산합니다.")
        if records:
            st.dataframe(pd.DataFrame(records[::-1]), hide_index=True)
    related_etfs.render(listing.at[key, "Code"], region, "direct")
