# 📦 박스권 스캐너

👉 **바로 사용하기: https://hawfinch1-box-scanner-app-xcrhdn.streamlit.app**

코스피·코스닥 전 종목 중 **최근 일정 기간(최소 5거래일 = 1주 이상) 좁은 범위에서 횡보 중인 종목**을 찾아주는 웹앱입니다.

## 기능
- 조건: 최소 박스 기간, 박스 폭(%), 상단·하단 터치 횟수, 종가/꼬리 기준, 최소 거래대금
- 결과 표: 박스 기간, 상단·하단, 박스 안 현재 위치(하단 근처/상단 근처 필터), CSV 다운로드
- 종목을 클릭하면 캔들 차트에 박스 구간을 표시

## 판별 방식
오늘을 끝으로 하는 최근 N거래일 구간에서
1. (최고가 − 최저가) / 최저가 ≤ 박스 폭 상한
2. 종가 회귀 추세선의 변화폭 ≤ 박스 높이 × 0.5 (꾸준한 상승·하락 제외)
3. 상단 20% 구간과 하단 20% 구간에 각각 최소 터치 횟수 이상 도달

을 모두 만족하는 가장 긴 N을 박스 기간으로 봅니다.

## 내 PC에서 실행
```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\streamlit run app.py
```

## 배포 (Streamlit Community Cloud, 무료)
1. 이 폴더를 GitHub 저장소에 올립니다 (`.venv`는 `.gitignore`로 제외됨).
2. https://share.streamlit.io 에서 GitHub로 로그인 → **Create app**.
3. 저장소·브랜치 선택, Main file path에 `app.py` 입력 → **Deploy**.
4. 몇 분 뒤 `https://<이름>.streamlit.app` 주소가 생기고, 누구나 접속할 수 있습니다.

## 데이터
- 종목 목록: FinanceDataReader(KRX)
- 일봉: 네이버 금융 차트 데이터
- 전 종목 시세는 서버에 30분 동안 캐시되어 모든 접속자가 공유합니다. 첫 스캔은 1분 안팎 걸립니다.

> 정보 제공용이며 투자 권유가 아닙니다.
