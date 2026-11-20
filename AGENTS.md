# AGENTS.md — 박스권 스캐너

먼저 `HANDOFF.md`(구성·실행·배포·확정 규칙·남은 일)와 `README.md`(사용자 설명)를 읽으세요.

## 실행·검사
- 설치: `python -m venv .venv` → `.venv\Scripts\pip install -r requirements-dev.txt`
- 실행: `.venv\Scripts\streamlit run app.py`
- 단위 검사(필수, 네트워크 불필요): `.venv\Scripts\python -m unittest test_outcomes test_history_cases -v`
- 전수 대조(네트워크·수 분): `.venv\Scripts\python verify.py`

## 규칙
- 비밀값·환경변수 없음. 원시 시세 파일을 저장소에 커밋하지 말 것(공개 저장소).
- `HANDOFF.md` 7장의 확정 규칙(돌파 기준, 기준점, 분모, 추정 불가 기준, 표현)은 사용자 확인 없이 바꾸지 말 것.
- 탐지·특징·유사도 계산에 기준점 이후 데이터를 쓰지 말 것. 바꾸면 "미래 데이터를 바꿔도 결과 불변" 검사를 추가할 것.
- 규칙을 바꾸면 새 규칙 버전 문자열을 만들어 이전 사례와 섞이지 않게 할 것.
- 화면 문구는 한국어, 결론 먼저·짧게. 미검증 수치를 "확률"로 표현하지 말 것.
- 커밋·푸시(=공개 사이트 자동 반영)는 사용자 확인 후. 보조 모듈을 바꿔 배포했다면 Streamlit Cloud 에서 Reboot 필요.
