import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import box

st.set_page_config(page_title="박스권 스캐너", page_icon="📦", layout="wide")

KST = ZoneInfo("Asia/Seoul")  # 배포 서버는 UTC라 한국 시간으로 표시
HISTORY_DAYS = 250  # 한 번에 받아 두는 일봉 수(약 1년, 120일선까지 계산 가능)
KR_MARKETS = ["KOSPI", "KOSDAQ", "KOSDAQ GLOBAL"]
MA_CHOICES = [5, 10, 20, 60, 120]
MA_COLORS = {5: "#f59f00", 10: "#37b24d", 20: "#e64980", 60: "#1c7ed6", 120: "#7048e8"}

REGIONS = {
    "kr": {"label": "국내 (코스피·코스닥)", "value_div": 1e8, "value_unit": "억원",
           "value_default": 10.0, "value_step": 5.0, "price_fmt": "%,d"},
    "us": {"label": "미국 (나스닥)", "value_div": 1e6, "value_unit": "백만달러",
           "value_default": 5.0, "value_step": 1.0, "price_fmt": "%.2f"},
}


def _progress_loader(listing: pd.DataFrame, fetcher, label: str) -> dict[str, pd.DataFrame]:
    bar = st.progress(0.0, text=f"{label} 시세 불러오는 중…")

    def tick(i: int, n: int) -> None:
        if i % 100 == 0 or i == n:  # 화면 갱신은 가끔만(매번 하면 느려짐)
            bar.progress(i / n, text=f"{label} 시세 불러오는 중… {i}/{n}")

    data = box.fetch_many(listing["Key"].tolist(), HISTORY_DAYS, fetcher, progress=tick)
    bar.empty()
    return data


@st.cache_data(ttl=1800, show_spinner=False)
def load_kr() -> tuple[pd.DataFrame, dict[str, pd.DataFrame], str]:
    """국내 전 종목 목록과 일봉을 받아 30분간 서버에 캐시(모든 접속자가 공유)."""
    listing = box.list_krx(KR_MARKETS)
    data = _progress_loader(listing, box.fetch_krx, "국내 전 종목")
    return listing, data, dt.datetime.now(KST).strftime("%m/%d %H:%M")


@st.cache_data(ttl=1800, show_spinner=False)
def load_us() -> tuple[pd.DataFrame, dict[str, pd.DataFrame], str]:
    listing = box.list_nasdaq()
    data = _progress_loader(listing, box.fetch_us, "나스닥 전 종목")
    return listing, data, dt.datetime.now(KST).strftime("%m/%d %H:%M")


st.title("📦 박스권 스캐너")
st.caption("일정 기간 동안 위아래로 좁은 범위에서 움직이는 주식을 찾아줍니다. 국내(코스피·코스닥)와 미국(나스닥)을 지원합니다.")

with st.sidebar:
    st.header("검색 조건")
    region = st.radio("지역", list(REGIONS), format_func=lambda k: REGIONS[k]["label"])
    R = REGIONS[region]
    if region == "kr":
        market_opt = st.multiselect("시장", ["KOSPI", "KOSDAQ"], default=["KOSPI", "KOSDAQ"])
    else:
        market_opt = ["NASDAQ"]

    st.subheader("📦 박스")
    min_days = st.slider("최소 박스 기간 (거래일)", 5, 60, 10,
                         help="5거래일 = 약 1주. 이 기간 이상 박스권을 유지한 종목만 표시합니다.")
    max_days = st.slider("최대 확인 기간 (거래일)", max(min_days, 20), 120, max(60, min_days),
                         help="박스가 이어진 기간을 이만큼 거슬러 올라가며 찾습니다.")
    max_width = st.slider("박스 폭 상한 (%)", 3.0, 30.0, 10.0, 0.5,
                          help="(상단-하단)/하단. 작을수록 더 좁고 단단한 박스입니다.")
    min_touches = st.slider("상단·하단 최소 터치 횟수", 1, 5, 2,
                            help="상단과 하단 근처에 각각 몇 번 이상 닿았는지. 높을수록 지지·저항이 뚜렷합니다.")
    basis = st.radio("가격 기준", ["종가", "고가·저가(꼬리 포함)"], horizontal=True)
    no_pinned = st.checkbox("가격 고정 종목 제외", value=True,
                            help="인수합병 발표 후 매수가 근처에 묶여 거의 움직이지 않는 종목처럼, "
                                 "하루 등락률 표준편차가 0.3% 미만인 종목을 뺍니다.")
    min_value = st.number_input(f"최소 평균 거래대금 ({R['value_unit']})", 0.0, 100000.0,
                                R["value_default"], R["value_step"], key=f"min_value_{region}",
                                help="거래가 너무 적은 종목은 박스처럼 보여도 의미가 없어 제외합니다.")

    st.subheader("📈 이동평균선")
    ma_periods = st.multiselect("사용할 이동평균선 (일)", MA_CHOICES, default=[5, 20, 60],
                                help="차트에 표시되고, 아래 조건에 쓰입니다.")
    ma_periods = sorted(ma_periods)
    cluster = st.checkbox("이평선 밀집 종목만", value=False, disabled=len(ma_periods) < 2,
                          help="선택한 이평선들이 한곳에 모여 있는(수렴) 종목만 남깁니다. 박스권 막바지에 자주 나타납니다.")
    max_spread = st.slider("밀집 허용 범위 (%)", 0.5, 10.0, 3.0, 0.5, disabled=not cluster,
                           help="선택한 이평선 중 가장 높은 값과 낮은 값의 차이(%).")
    ref_opt = st.selectbox("현재가 위치 기준선", ["사용 안 함"] + [f"{n}일선" for n in ma_periods])
    ref_side = "any"
    if ref_opt != "사용 안 함":
        ref_side = st.radio("현재가가", ["above", "below"], horizontal=True,
                            format_func=lambda s: f"{ref_opt} 위" if s == "above" else f"{ref_opt} 아래")

    run = st.button("🔍 스캔하기", type="primary", use_container_width=True)

if not market_opt:
    st.warning("시장을 하나 이상 선택하세요.")
    st.stop()

params = box.BoxParams(
    min_days=min_days, max_days=max_days, max_width_pct=max_width,
    min_touches=min_touches, use_close=(basis == "종가"), min_daily_vol_pct=0.3 if no_pinned else 0.0,
)
ma = box.MAParams(
    periods=ma_periods, cluster=cluster and len(ma_periods) >= 2, max_spread_pct=max_spread,
    ref_period=int(ref_opt.removesuffix("일선")) if ref_opt != "사용 안 함" else None, ref_side=ref_side,
)

if run:
    listing, all_hist, fetched_at = load_kr() if region == "kr" else load_us()
    markets = market_opt + (["KOSDAQ GLOBAL"] if "KOSDAQ" in market_opt else [])
    listing = listing[listing["Market"].isin(markets)]
    histories = {k: all_hist[k] for k in listing["Key"] if k in all_hist}
    with st.spinner("박스권 판별 중…"):
        st.session_state.update(
            result=box.scan(histories, listing, params, ma, min_value, R["value_div"]),
            histories=histories, region=region, ma=ma, scanned_at=fetched_at, universe=len(histories),
        )

if "result" not in st.session_state:
    st.info("왼쪽에서 조건을 정하고 **스캔하기**를 누르세요. 첫 스캔은 전 종목 시세를 받느라 30초~1분 걸리고, "
            "이후 30분 동안은 조건을 바꿔도 바로 결과가 나옵니다.")
    with st.expander("박스권은 어떻게 판별하나요?"):
        st.markdown("""
- **기간**: 오늘을 끝으로 하는 최근 N거래일 구간을 봅니다. 조건을 만족하는 가장 긴 N이 *박스 기간*입니다.
- **폭**: 구간의 최고가와 최저가 차이가 하단 대비 설정한 % 이내여야 합니다.
- **횡보**: 구간 종가에 직선 추세를 그렸을 때, 그 추세선이 움직인 폭이 박스 높이의 절반 이하여야 합니다(꾸준히 오르거나 내리는 종목 제외).
- **터치**: 상단 근처(박스 높이 상위 20%)와 하단 근처(하위 20%)에 각각 설정한 횟수 이상 닿아야 합니다. 연속으로 붙어 있는 날은 1회로 셉니다.
- **이평선 밀집**: 선택한 이동평균선들의 (최댓값−최솟값)/최솟값이 허용 범위 이내여야 합니다.
- **현재가 위치**: 오늘 종가가 기준 이동평균선 위(또는 아래)에 있어야 합니다.
""")
    st.stop()

res: pd.DataFrame = st.session_state["result"]
histories = st.session_state["histories"]
R = REGIONS[st.session_state["region"]]
ma_used: box.MAParams = st.session_state["ma"]

c1, c2, c3 = st.columns(3)
c1.metric("검색 종목 수", f"{st.session_state['universe']:,}")
c2.metric("박스권 종목", f"{len(res):,}")
c3.metric("시세 기준", st.session_state["scanned_at"])

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
cols = ["종목코드", "종목명", "시장", "박스기간(일)", "시작일", "현재가", "상단", "하단",
        "박스폭(%)", "박스내위치(%)", "상단터치", "하단터치", value_col]
if len(ma_used.periods) >= 2:
    cols.append("이평밀집도(%)")
if ma_used.ref_period:
    view = view.rename(columns={"기준이평 대비(%)": f"{ma_used.ref_period}일선 대비(%)"})
    cols.append(f"{ma_used.ref_period}일선 대비(%)")

pf = R["price_fmt"]
event = st.dataframe(
    view[cols],
    hide_index=True,
    use_container_width=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "현재가": st.column_config.NumberColumn(format=pf),
        "상단": st.column_config.NumberColumn(format=pf),
        "하단": st.column_config.NumberColumn(format=pf),
        "박스폭(%)": st.column_config.NumberColumn(format="%.1f"),
        "박스내위치(%)": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
        value_col: st.column_config.NumberColumn(format="%.1f"),
        "이평밀집도(%)": st.column_config.NumberColumn(format="%.2f"),
        f"{ma_used.ref_period}일선 대비(%)": st.column_config.NumberColumn(format="%+.2f"),
    },
)
st.download_button("CSV로 받기", view[cols].to_csv(index=False).encode("utf-8-sig"),
                   file_name=f"박스권_{dt.datetime.now(KST).date()}.csv", mime="text/csv")

st.divider()
rows = event.selection.rows if event and event.selection else []
row = view.iloc[rows[0]] if rows else view.iloc[0]
if not rows:
    st.caption("표에서 종목을 클릭하면 차트가 바뀝니다.")

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
    title=f"{row['종목명']} ({row['종목코드']}) · {row['박스기간(일)']}거래일 박스 · 폭 {row['박스폭(%)']:.1f}%",
    xaxis_rangeslider_visible=False, height=560, margin=dict(l=10, r=10, t=50, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1),
)
st.plotly_chart(fig, use_container_width=True)

st.caption("※ 시세는 네이버 금융 일봉 기준입니다(미국 종목은 현지 날짜). 장중에는 오늘 봉이 실시간으로 바뀝니다. "
           "이 도구는 정보 제공용이며 투자 권유가 아닙니다.")
