"""고정 박스의 최초 전략 신호 이후 확정 종가 경로 관찰."""
import pandas as pd


def strategy_cases(cases, histories, as_of, provisional, horizon):
    rows = []
    for _, case in cases.iterrows():
        prices = histories[case["Key"]].Close
        prices = prices[prices.index.date <= as_of]
        if provisional is not None:
            prices = prices[prices.index.date != provisional]
        prices = prices.loc[pd.Timestamp(case["탐지일"]):]
        upper, lower = case["상단"], case["하단"]
        middle = (upper + lower) / 2
        signals = []
        if case["방향"] == "상방":
            signals.append(("상방 돌파", pd.Timestamp(case["종료일"])))
        within = prices.loc[:pd.Timestamp(case["관찰종료일"])]
        if case["종료여부"]:
            within = within.iloc[:-1]
        recovery = within[(within.shift() <= lower) & (within > lower) & (within < middle)]
        if len(recovery):
            signals.append(("하단 회복", recovery.index[0]))
        for strategy, day in signals:
            if day.date() >= as_of:
                continue
            after = prices[prices.index > day].iloc[:horizon]
            result = "자료 부족"
            if strategy == "상방 돌파":
                if (after < upper).any():
                    result = "상단 아래 복귀"
                elif len(after) == horizon:
                    result = "상단 유지"
            else:
                hits = after[(after >= middle) | (after <= case["하방기준가"] * (1+1e-12))]
                if len(hits):
                    result = "중앙 도달" if hits.iloc[0] >= middle else "하방 먼저 돌파"
                elif len(after) == horizon:
                    result = "기간 내 미도달"
            rows.append({"전략": strategy, "종목": case["종목명"], "코드": case["Key"],
                         "신호일": day.date(), "결과": result})
    return pd.DataFrame(rows, columns=["전략","종목","코드","신호일","결과"])
