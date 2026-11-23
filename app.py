import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import box
import history_cases
import outcomes
import mobile_ui

st.set_page_config(page_title="박스권 스캐너", page_icon="📦", layout="wide")
mobile_ui.setup_mobile_ui()

KST = ZoneInfo("Asia/Seoul")  # 배포 서버는 UTC라 한국 시간으로 표시
HISTORY_DAYS = 250  # 한 번에 받아 두는 일봉 수(약 1년, 120일선까지 계산 가능)
KR_MARKETS = ["KOSPI", "KOSDAQ", "KOSDAQ GLOBAL"]
MA_CHOICES = [5, 10, 20, 60, 120]
MA_COLORS = {5: "#f59f00", 10: "#37b24d", 20: "#e64980", 60: "#1c7ed6", 120: "#7048e8"}
PINNED_VOL = 0.3  # 가격 고정 종목 판정 기준(일 등락률 표준편차 %)

REGIONS = {
    "kr": {"label": "국내 (코스피·코스닥)", "value_div": 1e8, "value_unit": "억원",
           "value_default": 10.0, "value_step": 5.0, "price_fmt": "%,d", "pfmt": "{:,.0f}",
           "close_note": "15:30 장 마감"},
    "us": {"label": "미국 (나스닥)", "value_div": 1e6, "value_unit": "백만달러",
           "value_default": 5.0, "value_step": 1.0, "price_fmt": "%.2f", "pfmt": "${:,.2f}",
           "close_note": "현지 16:00 장 마감"},
}


def _load(listing: pd.DataFrame, fetcher, label: str, region: str) -> tuple[pd.DataFrame, dict, dict]:
    bar = st.progress(0.0, text=f"{label} 시세 불러오는 중…")

    def tick(i: int, n: int) -> None:
        if i % 100 == 0 or i == n:  # 화면 갱신은 가끔만(매번 하면 느려짐)
            bar.progress(i / n, text=f"{label} 시세 불러오는 중… {i}/{n}")

    now = dt.datetime.now(dt.timezone.utc)
    data = box.fetch_many(listing["Key"].tolist(), HISTORY_DAYS, fetcher, progress=tick)
    bar.empty()
    meta = {
        "requested": len(listing),
        "fetched": len(data),
        "failed": [k for k in listing["Key"] if k not in data],
        "fetched_at": now.astimezone(KST).strftime("%Y-%m-%d %H:%M"),
        # 수집 시점에 장이 열려 있었다면, 그날 봉은 잠정값
        "prov_date": box.provisional_date(region, now),
    }
    return listing, data, meta


@st.cache_data(ttl=1800, show_spinner=False)
def load_kr():
    """국내 전 종목 목록과 일봉을 받아 30분간 서버에 캐시(모든 접속자가 공유)."""
    return _load(box.list_krx(KR_MARKETS), box.fetch_krx, "국내 전 종목", "kr")


@st.cache_data(ttl=1800, show_spinner=False)
def load_us():
    return _load(box.list_nasdaq(), box.fetch_us, "나스닥 전 종목", "us")


st.title("📦 박스권 스캐너")
st.caption("최근 일정 기간 좁은 가격 범위 안에서 오르내린 **횡보 후보** 종목을 찾아줍니다. "
           "국내(코스피·코스닥)와 미국(나스닥)을 지원합니다.")
# 휴대폰에서는 사이드바가 접혀 있어 스캔 버튼이 안 보이므로 본문에도 버튼을 둔다
main_run = st.button("🔍 스캔하기", type="primary", key="main_run",
                     help="‘설정 변경’에서 지정한 검색 조건으로 스캔합니다.")

# ───────────────────────── 사이드바: 기본 조건 → 스캔 버튼 → 세부 조건 ─────────────────────────
with st.sidebar:
    st.header("검색 조건")
    region = st.radio("지역", list(REGIONS), format_func=lambda k: REGIONS[k]["label"], horizontal=True)
    R = REGIONS[region]
    if region == "kr":
        market_opt = st.multiselect("시장", ["KOSPI", "KOSDAQ"], default=["KOSPI", "KOSDAQ"])
    else:
        market_opt = ["NASDAQ"]
    min_days = st.slider("최소 박스 기간 (거래일)", 5, 60, 10,
                         help="5거래일 = 약 1주. 이 기간 이상 박스권을 유지한 종목만 표시합니다.")
    max_width = st.slider("박스 폭 상한 (%)", 3.0, 30.0, 10.0, 0.5,
                          help="(상단-하단)/하단. 작을수록 더 좁고 단단한 박스입니다.")
    run = st.button("🔍 스캔하기", type="primary", use_container_width=True)
    st.caption("처음이라면 기본값 그대로 스캔해 보세요. 아래는 세부 조건입니다.")

    with st.expander("📦 세부 박스 조건"):
        max_days = st.slider("최대 확인 기간 (거래일)", max(min_days, 20), 120, max(60, min_days),
                             help="박스가 이어진 기간을 이만큼 거슬러 올라가며 찾습니다.")
        min_touches = st.slider("상단·하단 최소 터치 횟수", 1, 5, 2,
                                help="상단과 하단 근처에 각각 몇 번 이상 닿았는지. 높을수록 지지·저항이 뚜렷합니다.")
        basis = st.radio("가격 기준", ["종가", "고가·저가(꼬리 포함)"], horizontal=True)
        min_value = st.number_input(f"최소 평균 거래대금 ({R['value_unit']})", 0.0, 100000.0,
                                    R["value_default"], R["value_step"], key=f"min_value_{region}",
                                    help="거래가 너무 적은 종목은 박스처럼 보여도 의미가 없어 제외합니다.")
        no_pinned = st.checkbox("가격 고정 종목 제외", value=True,
                                help=f"인수합병 발표 후 매수가 근처에 묶여 거의 움직이지 않는 종목처럼, "
                                     f"하루 등락률 표준편차가 {PINNED_VOL}% 미만인 종목을 뺍니다.")
        drop_prov = st.checkbox("장중 잠정 봉 제외 (확정 종가로만 분석)", value=True,
                                help="장이 열려 있는 동안 오늘 봉은 계속 바뀝니다. 켜 두면 전 거래일까지의 "
                                     "확정 종가로만 판별합니다.")

    with st.expander("📈 이동평균선"):
        ma_periods = sorted(st.multiselect("사용할 이동평균선 (일)", MA_CHOICES, default=[5, 20, 60],
                                           help="차트에 표시되고, 아래 조건에 쓰입니다."))
        cluster = st.checkbox("이평선 밀집 종목만", value=False, disabled=len(ma_periods) < 2,
                              help="선택한 이평선들이 한곳에 모여 있는(수렴) 종목만 남깁니다.")
        max_spread = st.slider("밀집 허용 범위 (%)", 0.5, 10.0, 3.0, 0.5, disabled=not cluster,
                               help="선택한 이평선 중 가장 높은 값과 낮은 값의 차이(%).")
        ref_opt = st.selectbox("현재가 위치 기준선", ["사용 안 함"] + [f"{n}일선" for n in ma_periods])
        ref_side = "any"
        if ref_opt != "사용 안 함":
            ref_side = st.radio("현재가가", ["above", "below"], horizontal=True,
                                format_func=lambda s: f"{ref_opt} 위" if s == "above" else f"{ref_opt} 아래")

if not market_opt:
    st.warning("시장을 하나 이상 선택하세요.")
    st.stop()

params = box.BoxParams(
    min_days=min_days, max_days=max_days, max_width_pct=max_width, min_touches=min_touches,
    use_close=(basis == "종가"), min_daily_vol_pct=PINNED_VOL if no_pinned else 0.0,
)
ma = box.MAParams(
    periods=ma_periods, cluster=cluster and len(ma_periods) >= 2, max_spread_pct=max_spread,
    ref_period=int(ref_opt.removesuffix("일선")) if ref_opt != "사용 안 함" else None, ref_side=ref_side,
)

run = run or main_run
if run:
    st.session_state.pop("past_cases", None)
    st.session_state.pop("past_sig", None)
    listing, all_hist, meta = load_kr() if region == "kr" else load_us()
    markets = market_opt + (["KOSDAQ GLOBAL"] if "KOSDAQ" in market_opt else [])
    listing = listing[listing["Market"].isin(markets)]
    keys = set(listing["Key"])
    raw = {k: v for k, v in all_hist.items() if k in keys}
    histories, prep = box.prepare(raw, meta["prov_date"], drop_prov, min_days)
    with st.spinner("박스권 판별 중…"):
        st.session_state.update(
            result=box.scan(histories, listing, params, ma, min_value, R["value_div"]),
            histories=histories, region=region, ma=ma, params=params, min_value=min_value,
            listing=listing,
            status={**prep, "requested": len(listing), "fetched": len(raw),
                    "failed": len(keys) - len(raw), "fetched_at": meta["fetched_at"],
                    "prov_date": meta["prov_date"], "drop_prov": drop_prov},
        )

# 이전 버전에서 남은 세션(일부 키만 있음)은 결과가 없는 것으로 취급해 새로 스캔하게 한다
_NEEDED = ("result", "histories", "region", "ma", "params", "min_value", "listing", "status")
if not all(k in st.session_state for k in _NEEDED):
    st.info("**스캔하기**를 누르면 기본 조건으로 바로 찾습니다. 조건은 왼쪽 위 **설정 변경** 버튼에서 바꿀 수 있어요. "
            "첫 스캔은 전 종목 시세를 받느라 30초~1분 걸리고, "
            "이후 30분 동안은 조건을 바꿔도 바로 결과가 나옵니다.")
    with st.expander("박스권은 어떻게 판별하나요?", expanded=True):
        st.markdown("""
- **기간**: 마지막 거래일을 끝으로 하는 최근 N거래일 구간을 봅니다. 조건을 만족하는 가장 긴 N이 *박스 기간*입니다.
- **폭**: 구간의 최고가와 최저가 차이가 하단 대비 설정한 % 이내여야 합니다.
- **횡보**: 구간 종가에 직선 추세를 그렸을 때, 그 추세선이 움직인 폭이 박스 높이의 절반 이하여야 합니다(꾸준히 오르거나 내리는 종목 제외).
- **터치**: 상단 근처(박스 높이 상위 20%)와 하단 근처(하위 20%)에 각각 설정한 횟수 이상 닿아야 합니다. 연속으로 붙어 있는 날은 1회로 셉니다.
- **이평선 밀집**: 선택한 이동평균선들의 (최댓값−최솟값)/최솟값이 허용 범위 이내여야 합니다.
- **현재가 위치**: 마지막 종가가 기준 이동평균선 위(또는 아래)에 있어야 합니다.

검색 결과는 *과거 가격이 이런 모양이었다*는 뜻일 뿐, 앞으로 오르거나 내린다는 신호가 아닙니다.
""")
    st.stop()

# ───────────────────────── 결과 ─────────────────────────
res: pd.DataFrame = st.session_state["result"]
histories = st.session_state["histories"]
R = REGIONS[st.session_state["region"]]
ma_used: box.MAParams = st.session_state["ma"]
p_used: box.BoxParams = st.session_state["params"]
S = st.session_state["status"]

# 데이터 상태
if S["provisional"]:
    bar_state = "⚠️ 장중 잠정값"
    bar_help = f"수집 시점에 장이 열려 있어 마지막 봉({S['ref_date']})은 이후 바뀔 수 있습니다."
elif S["drop_prov"] and S["prov_date"] is not None:
    bar_state = "✅ 확정 종가"
    bar_help = f"장중이라 오늘({S['prov_date']}) 잠정 봉은 빼고 전 거래일 확정 종가까지만 분석했습니다."
else:
    bar_state = "✅ 확정 종가"
    bar_help = f"수집 시점에 장이 닫혀 있었습니다({R['close_note']} 이후)."

c1, c2, c3 = st.columns(3)
c1.metric("횡보 후보", f"{len(res):,}개", help="모든 조건을 통과한 종목 수")
c2.metric(f"마지막 봉 · {bar_state}", str(S["ref_date"]), help=bar_help)
c3.metric(f"분석 종목 (전체 {S['requested']:,})", f"{S['analyzed']:,}개",
          help="시세 없음·거래정지·기간 부족 종목을 뺀, 실제로 판별한 종목 수")

excluded = S["failed"] + S["stale"] + S["short"]
with st.expander(f"데이터 상태 · 수집 {S['fetched_at']} (KST) · 제외 {excluded:,}개"):
    st.markdown(f"""
| 항목 | 종목 수 |
|---|---:|
| 대상 종목 | {S['requested']:,} |
| 시세 없음 (수집 실패 또는 1년간 거래 없음) | {S['failed']:,} |
| 최근 거래일 시세 없음 (거래정지 등) | {S['stale']:,} |
| 기간 부족 (최소 박스 기간보다 짧은 상장 이력) | {S['short']:,} |
| **분석 완료** | **{S['analyzed']:,}** |

- 마지막 봉 날짜: **{S['ref_date']}** ({bar_state.split(' ', 1)[1]}) — {bar_help}
- 시세는 30분 동안 서버에 저장해 두고 재사용합니다. 미국 종목 날짜는 현지 기준입니다.
""")

st.caption("⚠️ 아래 결과는 *조건에 맞게 횡보한 종목*일 뿐, 상승·하락 신호나 투자 추천이 아닙니다.")

if res.empty:
    st.warning("조건에 맞는 종목이 없습니다. 박스 폭을 넓히거나 최소 기간·터치 횟수를 낮추거나, 이평선 조건을 풀어 보세요.")
    st.stop()

pos = st.segmented_control(
    "박스 안 현재 위치", ["전체", "하단 근처 (0~30%)", "중간 (30~70%)", "상단 근처 (70~100%)"],
    default="전체",
)
view = res
if pos == "하단 근처 (0~30%)":
    view = res[res["박스내위치(%)"] <= 30]
elif pos == "중간 (30~70%)":
    view = res[(res["박스내위치(%)"] > 30) & (res["박스내위치(%)"] < 70)]
elif pos == "상단 근처 (70~100%)":
    view = res[res["박스내위치(%)"] >= 70]
if view.empty:
    st.info("이 위치에 해당하는 종목이 없습니다.")
    st.stop()

value_col = f"평균거래대금({R['value_unit']})"
view = view.rename(columns={"평균거래대금": value_col})
ref_col = f"{ma_used.ref_period}일선 대비(%)" if ma_used.ref_period else None
if ref_col:
    view = view.rename(columns={"기준이평 대비(%)": ref_col})
# 핵심 열(종목명·폭·기간·위치)을 앞에 둔다. 좁은 화면에서도 먼저 보이도록.
cols = ["종목명", "박스폭(%)", "박스기간(일)", "박스내위치(%)", "현재가", "상단", "하단",
        "상단터치", "하단터치", value_col]
if len(ma_used.periods) >= 2:
    cols.append("이평밀집도(%)")
if ref_col:
    cols.append(ref_col)
cols += ["시작일", "종목코드", "시장"]

pf = R["price_fmt"]
event = st.dataframe(
    view[cols],
    hide_index=True,
    use_container_width=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "종목명": st.column_config.TextColumn(pinned=True),
        "박스폭(%)": st.column_config.NumberColumn("박스폭", format="%.1f%%"),
        "박스기간(일)": st.column_config.NumberColumn("기간(일)"),
        "박스내위치(%)": st.column_config.ProgressColumn("박스 안 위치", min_value=0, max_value=100, format="%.0f%%"),
        "현재가": st.column_config.NumberColumn("마지막 종가", format=pf),
        "상단": st.column_config.NumberColumn(format=pf),
        "하단": st.column_config.NumberColumn(format=pf),
        value_col: st.column_config.NumberColumn(format="%.1f"),
        "이평밀집도(%)": st.column_config.NumberColumn(format="%.2f"),
        **({ref_col: st.column_config.NumberColumn(format="%+.2f")} if ref_col else {}),
    },
)
st.download_button("CSV로 받기", view[cols].to_csv(index=False).encode("utf-8-sig"),
                   file_name=f"박스권_{S['ref_date']}.csv", mime="text/csv")

st.divider()
rows = event.selection.rows if event and event.selection else []
row = view.iloc[rows[0]] if rows else view.iloc[0]
if not rows:
    st.caption("표에서 종목을 클릭하면 아래 선정 이유와 차트가 바뀝니다.")

st.subheader(f"{row['종목명']} ({row['종목코드']})")

# 선정 이유: 조건별 실제 값과 기준을 나란히
pfmt = R["pfmt"]
reasons = [
    ("분석 기간", f"{row['시작일']} ~ {S['ref_date']} ({int(row['박스기간(일)'])}거래일)",
     f"≥ {p_used.min_days}거래일"),
    ("박스 상단 / 하단", f"{pfmt.format(row['상단'])} / {pfmt.format(row['하단'])}",
     "구간 " + ("종가" if p_used.use_close else "고가·저가") + " 최고/최저"),
    ("박스 폭", f"{row['박스폭(%)']:.1f}%", f"≤ {p_used.max_width_pct:g}%"),
    ("추세 (회귀선 이동폭 ÷ 박스 높이)", f"{row['추세비율']:.2f}", f"≤ {p_used.max_drift_ratio:g}"),
    ("상단 / 하단 접촉", f"{int(row['상단터치'])}회 / {int(row['하단터치'])}회", f"각 ≥ {p_used.min_touches}회"),
    ("현재 위치", f"박스 높이의 {row['박스내위치(%)']:.0f}% (마지막 종가 {pfmt.format(row['현재가'])})", "참고용"),
    ("평균 거래대금", f"{row[value_col]:,.1f} {R['value_unit']}",
     f"≥ {st.session_state['min_value']:g} {R['value_unit']}"),
    ("일 등락률 표준편차", f"{row['일변동성(%)']:.2f}%",
     f"≥ {p_used.min_daily_vol_pct:g}%" if p_used.min_daily_vol_pct else "조건 없음"),
]
if len(ma_used.periods) >= 2:
    reasons.append(("이평선 밀집도 (" + "·".join(f"{n}" for n in ma_used.periods) + "일선)",
                    f"{row['이평밀집도(%)']:.2f}%", f"≤ {ma_used.max_spread_pct:g}%" if ma_used.cluster else "조건 없음"))
if ref_col:
    side = "위" if ma_used.ref_side == "above" else "아래"
    reasons.append((f"{ma_used.ref_period}일선 대비", f"{row[ref_col]:+.2f}%", f"{ma_used.ref_period}일선 {side}"))

miss = box.missing_days(histories[row["Key"]], S["calendar"], row["시작일"])
c_left, c_right = st.columns([3, 2])
with c_left:
    st.markdown("**선정 이유** — 모든 조건 통과")
    st.dataframe(pd.DataFrame(reasons, columns=["항목", "값", "기준"]), hide_index=True, use_container_width=True)
with c_right:
    st.markdown("**데이터 상태**")
    st.dataframe(pd.DataFrame([
        ("마지막 봉 날짜", str(S["ref_date"])),
        ("확정 여부", bar_state),
        ("수집 시각", f"{S['fetched_at']} KST"),
        ("박스 구간 누락일", (f"{miss}일 (거래정지 또는 수집 누락)" if miss else "없음")),
        ("보유 시세", f"{len(histories[row['Key']])}거래일"),
    ], columns=["항목", "값"]), hide_index=True, use_container_width=True)

# 차트
full = histories[row["Key"]]
show_n = max(60, int(row["박스기간(일)"]) * 3)  # 박스가 잘 보이도록 최근 구간만
mas = {n: full["Close"].rolling(n).mean().tail(show_n) for n in ma_used.periods}
df = full.tail(show_n)

fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.03)
fig.add_trace(go.Candlestick(
    x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
    increasing_line_color="#e5484d", decreasing_line_color="#3e63dd", name="일봉", showlegend=False,
), row=1, col=1)
for n, s in mas.items():
    fig.add_trace(go.Scatter(x=s.index, y=s, mode="lines", name=f"{n}일선",
                             line=dict(width=1.4, color=MA_COLORS.get(n))), row=1, col=1)
fig.add_shape(type="rect", x0=pd.Timestamp(row["시작일"]), x1=df.index[-1], y0=row["하단"], y1=row["상단"],
              fillcolor="rgba(255,193,7,0.15)", line=dict(color="rgba(255,160,0,0.8)", width=1.5), row=1, col=1)
vol_colors = ["#e5484d" if c >= o else "#3e63dd" for o, c in zip(df["Open"], df["Close"])]
fig.add_trace(go.Bar(x=df.index, y=df["Volume"], marker_color=vol_colors, name="거래량", showlegend=False),
              row=2, col=1)
gaps = pd.date_range(df.index[0], df.index[-1]).difference(df.index)  # 주말·휴장일 공백 제거
fig.update_xaxes(rangebreaks=[dict(values=gaps)])
fig.update_layout(
    title=f"{int(row['박스기간(일)'])}거래일 박스 · 폭 {row['박스폭(%)']:.1f}% (노란 영역)",
    xaxis_rangeslider_visible=False, height=560, margin=dict(l=10, r=10, t=50, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1),
)
mobile_ui.render_chart(
    fig, f"{int(row['박스기간(일)'])}거래일 박스 · 폭 {row['박스폭(%)']:.1f}% (노란 영역)",
    key=f"price_chart_{row['Key']}",
)

st.caption("※ 시세는 네이버 금융 일봉 기준입니다. 박스권은 과거 가격 패턴이며 향후 방향을 알려주지 않습니다. "
           "이 도구는 정보 제공용이며 투자 권유가 아닙니다.")

# ───────────────────────── 과거 비슷한 박스의 돌파 결과 ─────────────────────────
st.divider()
st.subheader("과거 비슷한 박스는 어디로 뚫었나")

c_b, c_h = st.columns(2)
band = c_b.select_slider("돌파 확인폭 b", options=[2.0, 2.5, 3.0], value=3.0, format_func=lambda v: f"{v:g}%",
                         help="상방: 종가 ≥ 상단×(1+b). 하방: 종가 ≤ 하단×(1−b). 그 사이는 박스 유지로 봅니다.")
horizon = c_h.radio("기간", outcomes.HORIZONS, index=1, horizontal=True, format_func=lambda h: f"{h}일 안에")

listing_s = st.session_state.get("listing", pd.DataFrame())
labels = ({str(r.Key): f"{r.Name} ({r.Code})" for r in listing_s.itertuples()} if not listing_s.empty else {})
auto_keys = list(dict.fromkeys([row["Key"]] + view["Key"].head(20).tolist()))[:21]
pool_key = f"pool_{S['fetched_at']}_{st.session_state['region']}_{pos}"
pool = st.session_state.get(pool_key) or auto_keys
if row["Key"] not in pool:
    pool = [row["Key"]] + list(pool)

# 수집(자동). 같은 종목·조건·돌파폭이면 다시 계산하지 않는다.
sig = (tuple(sorted(pool)), band, S["fetched_at"], repr(p_used), repr(ma_used), st.session_state["min_value"])
if st.session_state.get("past_sig") != sig:
    with st.spinner(f"과거 사례 수집 중… ({len(pool)}종목)"):
        errs: list = []
        st.session_state["past_cases"] = history_cases.collect_cases(
            {k: histories[k] for k in pool if k in histories}, p_used, ma_used,
            st.session_state["min_value"], R["value_div"], S["prov_date"],
            listing=listing_s, calendar=S["calendar"], errors=errs, rule="v2", band_pct=band,
            collected_at=dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"))
        st.session_state["past_errors"] = errs
        st.session_state["past_sig"] = sig
cases = st.session_state["past_cases"]

_own = histories[row["Key"]]
if S["prov_date"] is not None:  # 수집은 잠정 봉을 항상 빼므로 확정된 마지막 봉 기준으로 맞춘다
    _own = _own[_own.index.date != S["prov_date"]]
target = history_cases.current_case(cases, row["Key"], _own.index[-1].date()) if len(_own) else None

tol_days = st.session_state.get("tol_days", 10)
tol_width = st.session_state.get("tol_width", 3.0)
tol_pos = st.session_state.get("tol_pos", 25.0)
base = None

if target is None:
    st.info(f"**{row['종목명']}**은 돌파폭 {band:g}% 기준으로 지금 진행 중인 박스가 없어 계산하지 않았습니다 "
            "(최초 탐지 때의 경계에서 이미 돌파한 상태).")
else:
    age = int(target["탐지후관찰봉수"])
    others = cases[cases["사례ID"] != target["사례ID"]]
    others = others[pd.to_datetime(others["탐지일"]) < pd.Timestamp(S["ref_date"])]
    similar = history_cases.similar_cases(others, target, tol_days, tol_width, tol_pos, S["ref_date"])
    sim_cls = outcomes.classify(similar, age)
    s_sim = outcomes.summarize(sim_cls, horizon)
    if s_sim["estimable"]:
        base, basis_label = sim_cls, "비슷한 사례"
    else:
        base, basis_label = outcomes.classify(others, age), f"수집한 {len(pool)}종목 전체 사례"
    summary = outcomes.summarize(base, horizon)

    if summary["estimable"]:
        pc, ci, cnt = summary["pct"], summary["ci"], summary["counts"]
        m1, m2, m3 = st.columns(3)
        m1.metric(f"▲ 위로 돌파 ({cnt['상방']}건)", f"{pc['상방']:.0f}%")
        m2.metric(f"▼ 아래로 돌파 ({cnt['하방']}건)", f"{pc['하방']:.0f}%")
        m3.metric(f"■ 못 뚫음 ({cnt['미돌파']}건)", f"{pc['미돌파']:.0f}%")
        note = ("" if basis_label == "비슷한 사례"
                else f" · 비슷한 사례는 {s_sim['n']}건({s_sim['stocks']}종목)뿐이라 전체 사례로 계산")
        st.caption(f"과거 {basis_label} **{summary['n']}건**({summary['stocks']}종목) 중 {horizon}일 안의 결과 · "
                   f"95% 범위 위로 {ci['상방'][0]:.0f}–{ci['상방'][1]:.0f}%, "
                   f"아래로 {ci['하방'][0]:.0f}–{ci['하방'][1]:.0f}%{note}")
    else:
        st.metric("결과", "추정 불가")
        st.caption(f"과거 사례가 {summary['n']}건({summary['stocks']}종목)뿐이라 비율을 내지 않습니다 "
                   f"(기준: {outcomes.MIN_N}건·{outcomes.MIN_STOCKS}종목 이상).")

    st.subheader("돌파까지 얼마나 걸렸나")
    timing = outcomes.breakout_timing(base, age, horizon)

    def _days_value(stats):
        if not stats["n"]:
            return "돌파 사례 없음"
        return f"{stats['mean']:.1f}거래일" if stats["estimable"] else "추정 불가"

    t_all, t_up, t_down = st.columns(3)
    for column, label, stats in (
        (t_all, "돌파 평균 (양방향)", timing),
        (t_up, "위로 돌파 평균", timing["by_direction"]["상방"]),
        (t_down, "아래로 돌파 평균", timing["by_direction"]["하방"]),
    ):
        column.metric(label, _days_value(stats))
        column.caption(f"돌파 {stats['n']}건 · {stats['stocks']}종목")
    median_note = (f" · 중앙값 {timing['median']:g}거래일" if timing["estimable"] else "")
    st.caption(
        f"과거 {basis_label} 중 같은 경과 시점부터 **{horizon}거래일 안에 실제 돌파한 사례만**의 추가 소요 기간{median_note}. "
        f"해당 기간 미돌파 {timing['counts']['미돌파']}건·데이터 부족 {timing['counts']['데이터부족']}건은 평균에서 제외함. "
        "짧은 기간에 돌파한 사례만의 평균이므로 현재 종목의 예상 돌파일이나 모든 박스의 평균 대기 시간이 아님."
    )
    st.caption(
        f"단위는 달력 날짜가 아닌 관측된 일봉 수임(주말·휴장·거래정지 누락일 제외). "
        f"평균은 방향별로도 돌파 {outcomes.MIN_N}건·{outcomes.MIN_STOCKS}종목 이상일 때 표시함."
    )

    def _cell(s, lab):
        if not s["estimable"]:
            return "–"
        lo, hi = s["ci"][lab]
        return f"{s['pct'][lab]:.0f}% ({lo:.0f}–{hi:.0f})"

    tbl = []
    for h in outcomes.HORIZONS:
        s = outcomes.summarize(base, h)
        t = outcomes.breakout_timing(base, age, h)
        tbl.append({"기간": f"{h}일 안에", "위로": _cell(s, "상방"), "아래로": _cell(s, "하방"),
                    "못 뚫음": _cell(s, "미돌파"), "사례(종목)": f"{s['n']}({s['stocks']})",
                    "데이터 부족": s["counts"]["데이터부족"],
                    "돌파 평균(추가 거래일)": f"{t['mean']:.1f}" if t["estimable"] else "–",
                    "평균 대상(종목)": f"{t['n']}({t['stocks']})"})
    st.dataframe(pd.DataFrame(tbl), hide_index=True, use_container_width=True)
    st.caption(f"괄호는 95% 범위. 과거에 관측된 비율이며 {row['종목명']}의 앞날을 맞히도록 검증된 확률은 아닙니다. "
               f"기준점: 탐지 후 {age}봉째까지 돌파하지 않은 시점부터.")

# ── 세부 정보(접어 둠) ──
with st.expander("계산 방법과 한계"):
    st.markdown(f"""
- **돌파**: 탐지일의 상단(U)·하단(L)을 고정하고, 확정 종가가 U×(1+{band:g}%) 이상이면 위로, L×(1−{band:g}%) 이하이면 아래로 돌파. 먼저 일어난 쪽만 셉니다. 장중 꼬리는 무시합니다.
- **기준점**: 이 종목이 탐지 후 e봉째까지 돌파하지 않았다면, 과거 사례도 e봉째까지 돌파하지 않은 것만 골라 그 시점부터 기간을 셉니다.
- **비율**: 분모는 기간 안에 결과를 판정할 수 있는 사례(위로+아래로+못 뚫음). 관측이 기간보다 짧고 돌파도 없던 사례는 '데이터 부족'으로 따로 셉니다.
- **95% 범위**: 종목 단위로 다시 뽑아 계산했습니다. 같은 날 시장 전체가 함께 움직인 영향은 다 반영하지 못합니다.
- **추정 불가**: 판정 가능 사례 {outcomes.MIN_N}건 미만이거나 종목 {outcomes.MIN_STOCKS}개 미만.
- **돌파 소요 기간**: 같은 경과 시점부터 선택한 기간 안에 실제 돌파한 사례의 추가 관측 봉수 평균·중앙값. 미돌파·데이터 부족은 평균에 넣지 않으며 제외 건수를 표시합니다. 전체·방향별 각각 돌파 {outcomes.MIN_N}건·{outcomes.MIN_STOCKS}종목 미만이면 평균도 추정 불가입니다. 기간 밖에서 돌파한 사례도 해당 기간의 평균에는 넣지 않습니다.
- **비슷한 사례**: 탐지 당시 기간 ±{tol_days}봉, 박스 폭 ±{tol_width:g}%p, 위치 ±{tol_pos:g}%p. 부족하면 수집한 종목의 전체 사례로 계산하고 그렇게 표시합니다.
- **데이터**: 약 250개 일봉(1년)과 현재 상장 종목만 사용해 상장폐지 종목이 빠집니다. 분할 반영 수정주가, 배당 미반영. 관측 봉수는 거래정지일을 세지 않습니다.
- 규칙 버전: `{history_cases.rule_version('v2', band)}`
""")

with st.expander("비슷한 사례 기준 조정"):
    a, b, c = st.columns(3)
    a.number_input("탐지 당시 기간 차이 ±(봉)", 0, 120, 10, key="tol_days")
    b.number_input("박스 폭 차이 ±(%p)", 0.0, 30.0, 3.0, key="tol_width")
    c.number_input("박스 내 위치 차이 ±(%p)", 0.0, 100.0, 25.0, key="tol_pos")
    st.caption("사용자 비교 조건이며 예측 성능이 검증된 기준이 아닙니다.")

with st.expander(f"수집 대상 {len(pool)}종목 (표 상위 20개 자동 선택)"):
    st.multiselect("수집 대상", sorted(histories), default=auto_keys, key=pool_key,
                   format_func=lambda k: labels.get(k, k), max_selections=21, label_visibility="collapsed")
    errs = st.session_state.get("past_errors", [])
    if errs:
        st.warning(f"시세 오류로 {len(errs)}종목 제외: " + ", ".join(labels.get(k, k) for k, _ in errs))
    rng = []
    for k in pool:
        h = histories.get(k)
        if h is None or not len(h):
            continue
        h = h[h.index.date != S["prov_date"]] if S["prov_date"] else h
        rng.append({"종목": labels.get(k, k), "시세 시작일": h.index[0].date(), "시세 마지막일": h.index[-1].date(),
                    "보유 봉수": len(h), "누락일": box.missing_days(h, S["calendar"], h.index[0])})
    st.dataframe(pd.DataFrame(rng), hide_index=True, use_container_width=True)

with st.expander(f"사례 목록과 CSV ({len(cases)}건)"):
    if cases.empty:
        st.info("수집된 사례가 없습니다.")
    else:
        hide = ["검색조건JSON", "Key"]
        done, open_ = cases[cases["종료여부"]], cases[~cases["종료여부"]]
        t1, t2 = st.tabs([f"돌파 {len(done)}건", f"관찰 중 {len(open_)}건"])
        t1.dataframe(done.drop(columns=hide).rename(columns={"탐지후관찰봉수": "탐지→돌파 봉수",
                                                              "종료일": "돌파일", "종료종가": "돌파종가"}),
                     hide_index=True, use_container_width=True)
        t2.caption("관찰 봉수는 마지막 관측일까지 센 값이며 남은 기간이 아닙니다.")
        t2.dataframe(open_.drop(columns=hide + ["종료일", "종료종가"])
                     .rename(columns={"탐지후관찰봉수": "탐지 후 관찰 봉수"}), hide_index=True, use_container_width=True)
        export = cases if base is None else cases.merge(
            base[["사례ID"] + [f"결과{h}" for h in outcomes.HORIZONS]], on="사례ID", how="left")
        d1, d2 = st.columns(2)
        d1.download_button("CSV (원본)", history_cases.to_csv_bytes(export), "박스권_과거사례.csv", "text/csv")
        d2.download_button("CSV (엑셀용)", history_cases.to_csv_bytes(export, excel=True),
                           "박스권_과거사례_엑셀용.csv", "text/csv", help="엑셀에서도 종목코드 앞자리 0 유지")
