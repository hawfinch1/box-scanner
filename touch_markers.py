"""박스 집계와 동일한 조건으로 연속 터치의 첫 봉을 표시한다."""
import pandas as pd
import plotly.graph_objects as go


def touch_points(frame, upper, lower, params):
    points = []
    zone = (upper - lower) * params.touch_zone
    padding = (upper - lower) * 0.3
    for side, column, threshold, marker_y in (
        ("상단", "Close" if params.use_close else "High", upper - zone, upper + padding),
        ("하단", "Close" if params.use_close else "Low", lower + zone, max(0, lower - padding)),
    ):
        prices = frame[column]
        mask = prices >= threshold if side == "상단" else prices <= threshold
        starts = mask & ~mask.shift(1, fill_value=False)
        for date, price in prices[starts].items():
            points.append({"side": side, "date": date, "price": float(price),
                           "marker_y": marker_y, "basis": column, "threshold": threshold})
    return points


def add_touch_markers(fig, boxes, params, visible_dates):
    """boxes는 (전체 형성 구간, 상단, 하단)의 목록. 화면 밖 첫 터치는 재집계하지 않는다."""
    points = [point for frame, upper, lower in boxes
              for point in touch_points(frame, upper, lower, params)
              if point["date"] in visible_dates]
    for side, color, symbol in (
        ("상단", "#e03131", "triangle-down"), ("하단", "#1971c2", "triangle-up"),
    ):
        touches = [point for point in points if point["side"] == side]
        if not touches:
            continue
        x, y = [], []
        for point in touches:
            x.extend([point["date"], point["date"], None])
            y.extend([point["price"], point["marker_y"], None])
        fig.add_trace(go.Scatter(x=x, y=y, mode="lines", line=dict(color=color, width=1, dash="dot"),
                                 showlegend=False, hoverinfo="skip"), row=1, col=1)
        dates = [point["date"] for point in touches]
        details = [[point["price"], point["basis"], point["threshold"]] for point in touches]
        hover = (f"{side} 터치 · 연속 구간 첫 봉<br>%{{x|%Y-%m-%d}}"
                 "<br>판정 가격 %{customdata[0]:,.2f}<br>기준 %{customdata[1]}"
                 "<br>접촉 기준값 %{customdata[2]:,.2f}<extra></extra>")
        fig.add_trace(go.Scatter(x=dates, y=[point["price"] for point in touches], mode="markers",
                                 marker=dict(symbol="circle-open", size=5, color=color, line=dict(width=1)),
                                 showlegend=False, customdata=details, hovertemplate=hover), row=1, col=1)
        fig.add_trace(go.Scatter(x=dates, y=[point["marker_y"] for point in touches], mode="markers",
                                 marker=dict(symbol=symbol, size=10, color=color), line=dict(color=color),
                                 name=f"{side} 터치", showlegend=True, customdata=details,
                                 hovertemplate=hover), row=1, col=1)
    return points
