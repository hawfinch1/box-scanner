"""확정 일봉 기준 관찰 지표."""
import numpy as np


ALIGNMENT_RULE_VERSION = "ordered-ma-first-day-v1"


def indicators(df, include_120=False):
    c = df.Close.to_numpy(float)
    n = len(c)
    out = dict.fromkeys(("데드크로스", "골든크로스", "20일선 위치", "20일선 방향", "60일선 방향", "Supertrend", "밴드 폭", "하단 밴드"), "자료 부족")
    def direction(diff):
        return "상승" if diff > 0 else "하락" if diff < 0 else "보합"
    for period in (20, 60):
        if n >= period + 5:
            out[f"{period}일선 방향"] = direction(c[-period:].mean() - c[-period-5:-5].mean())
    if n >= 60:
        diff = c[-20:].mean() - c[-60:].mean()
        out["20일선 위치"] = "60일선 위" if diff > 0 else "60일선 아래" if diff < 0 else "60일선과 같음"
    periods = (5, 20, 60, 120) if include_120 else (5, 20, 60)
    if n >= periods[-1] + 1:
        today = np.array([c[-period:].mean() for period in periods])
        previous = np.array([c[-period-1:-1].mean() for period in periods])
        for label, sign in (("골든크로스", -1), ("데드크로스", 1)):
            now_ordered = bool((np.diff(today) * sign > 0).all())
            was_ordered = bool((np.diff(previous) * sign > 0).all())
            out[label] = ("유지" if was_ordered else "오늘 완성") if now_ordered else "미충족"
    if n >= 21:
        now, prev = c[-20:], c[-21:-1]
        delta = now.std()/now.mean() - prev.std()/prev.mean()
        out["밴드 폭"] = "확대" if delta > 0 else "축소" if delta < 0 else "동일"
        lower, old = now.mean()-2*now.std(), prev.mean()-2*prev.std()
        out["하단 밴드"] = ("안으로 복귀" if c[-2] < old and lower <= c[-1] <= now.mean()+2*now.std()
                         else "하단 밖" if c[-1] < lower else "하단 이상")
    if n >= 10:
        h, l = df.High.to_numpy(float), df.Low.to_numpy(float)
        previous = np.r_[c[0], c[:-1]]
        tr = np.maximum(h-l, np.maximum(abs(h-previous), abs(l-previous)))
        atr = tr[:10].mean()
        upper, lower = (h[9]+l[9])/2+3*atr, (h[9]+l[9])/2-3*atr
        rising = changed = False
        for i in range(10,n):
            atr = (9*atr+tr[i])/10
            mid = (h[i]+l[i])/2
            u, d = mid+3*atr, mid-3*atr
            upper = u if c[i-1]>upper else min(u, upper)
            lower = d if c[i-1]<lower else max(d, lower)
            trend = c[i]>=lower if rising else c[i]>upper
            changed, rising = trend != rising, trend
        out["Supertrend"] = ("상승" if rising else "하락") + (" 전환" if changed else "")
    return out
