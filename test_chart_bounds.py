import unittest
from unittest.mock import patch

import pandas as pd
from plotly.subplots import make_subplots
import plotly.graph_objects as go

import mobile_ui


class ChartBoundsTests(unittest.TestCase):
    def test_dates_and_nonnegative_axes_survive_zoom_setup(self):
        dates = pd.date_range("2026-01-01", periods=3)
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True)
        fig.add_trace(go.Candlestick(x=dates, open=[10]*3, high=[12]*3,
                                     low=[9]*3, close=[11]*3), row=1, col=1)
        fig.add_trace(go.Bar(x=dates, y=[100]*3), row=2, col=1)
        with patch.object(mobile_ui, "_chart_component") as component:
            mobile_ui.render_chart(fig, "test", key="test")
            layout = component.return_value.call_args.kwargs["data"]["figure"]["layout"]
        for axis in ("xaxis", "xaxis2"):
            self.assertEqual(layout[axis]["minallowed"], dates[0].isoformat())
            self.assertEqual(layout[axis]["maxallowed"], dates[-1].isoformat())
        for axis in ("yaxis", "yaxis2"):
            self.assertEqual(layout[axis]["minallowed"], 0)
