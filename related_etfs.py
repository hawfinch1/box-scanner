"""운용사 공시에서 확인한 ETF 연결. 국내 과거 공시와 갱신형 공시를 구분한다."""
import io
from urllib.parse import quote

ETF_LOOKUP_VERSION = 1

import pandas as pd
import requests
import streamlit as st

SPY = "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"
KODEX = "https://www.samsungfund.com/sheet/20260805/2ETF01_20260731.pdf"
TIGER = "https://investments.miraeasset.com/tigeretf/upload/etf/20250804095349008734.pdf"
DIREXION = "https://www.direxion.com/product/daily-tsla-bull-and-bear-leveraged-single-stock-etfs"


@st.cache_data(ttl=3600, show_spinner=False)
def spy_holdings():
    response = requests.get(SPY, timeout=10)
    response.raise_for_status()
    sheet = pd.read_excel(io.BytesIO(response.content), header=None)
    if sheet.iat[1, 1] != "SPY" or sheet.iat[4, 1] != "Ticker" or sheet.iat[4, 4] != "Weight":
        raise ValueError("공시 형식 변경")
    date = pd.to_datetime(str(sheet.iat[2, 1]).removeprefix("As of "), format="%d-%b-%Y").date()
    return date, dict(zip(sheet.iloc[5:, 1], pd.to_numeric(sheet.iloc[5:, 4], errors="coerce")))


def render(code, region, key):
    if not st.checkbox("관련 ETF 보기", key=f"etfs_{key}_{region}_{code}"):
        return
    st.caption("조회 범위 · SPY 운용사 편입표, 국내 과거 공시 일부, 테슬라 일간 추종 상품 2개")
    st.link_button(f"ETF CHECK에서 {code} 편입 ETF 바로 확인",
                   f"https://www.etfcheck.co.kr/mobile/searchPdf/{quote(str(code), safe='')}")
    st.caption("ETF CHECK 결과 조회에는 해당 사이트 로그인이 필요합니다. 아래 표는 별도로 확보한 일부 자료입니다.")
    rows = []

    def add(market, fund, relation, date, source):
        rows.append({"상장 시장": market, "ETF": fund, "종목과의 관계": relation,
                     "자료 기준일": str(date), "운용사 자료": source})

    if region == "us":
        try:
            date, weights = spy_holdings()
            if pd.notna(weights.get(code)):
                add("미국", "SPY", f"직접 편입 {weights[code]:.2f}%", date, SPY)
        except (requests.RequestException, ValueError, IndexError, OSError):
            st.warning("SPY 편입표를 확인하지 못했습니다. 다시 조회해 주세요.")
    if region == "kr" and code == "005930":
        add("국내", "Kodex 200 (069500)", "과거 공시 편입 32.72%", "2026-07-31", KODEX)
    if region == "us" and code == "TSLA":
        add("국내", "TIGER 테슬라채권혼합Fn (447770)", "과거 공시 편입 29.73%", "2025-07-31", TIGER)
        for ticker, target in [("TSLL", "+2배"), ("TSLS", "−1배")]:
            add("미국", ticker, f"테슬라 일간 {target} 목표", "2026-11-27 상품 설명 확인", DIREXION)
        st.caption("일간 목표 배율은 여러 날 보유한 누적 수익률에 그대로 적용되지 않습니다.")
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True,
                     column_config={"운용사 자료": st.column_config.LinkColumn(display_text="공시 열기")})
    else:
        st.caption("현재 조회 가능한 자료에서 연결 상품을 찾지 못했습니다.")
