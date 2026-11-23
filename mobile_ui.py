"""Mobile presentation only; scanner parameters and calculations stay in app.py."""

import json
from pathlib import Path

import streamlit as st
import streamlit.components.v2 as components
from plotly.offline import get_plotlyjs

_ASSETS = Path(__file__).parent / "ui"


@st.cache_resource
def _settings_component():
    return components.component(
        "box_scanner_settings_label",
        js="""
        export default function() {
            const label = () => {
                for (const [testid, text] of [
                    ['stSidebarCollapsedControl', '설정 변경'],
                    ['stExpandSidebarButton', '설정 변경'],
                    ['stSidebarCollapseButton', '설정 닫기']
                ]) {
                    const control = document.querySelector(`[data-testid="${testid}"]`);
                    const button = control?.matches('button') ? control : control?.querySelector('button');
                    if (button && button.getAttribute('aria-label') !== text) {
                        button.setAttribute('aria-label', text);
                        button.setAttribute('title', text);
                    }
                }
            };
            label();
            const observer = new MutationObserver(label);
            observer.observe(document.body, {childList: true, subtree: true});
            return () => observer.disconnect();
        }
        """,
    )


def setup_mobile_ui():
    st.html("""
    <style>
    [data-testid="stSidebarCollapsedControl"] button,
    button[data-testid="stExpandSidebarButton"],
    [data-testid="stSidebarCollapseButton"] button {
        width: auto !important; min-width: 108px; min-height: 44px;
        padding: 8px 12px !important; gap: 0;
        border: 1px solid #d1d5db; border-radius: 8px;
        background: var(--background-color, white); color: inherit;
    }
    [data-testid="stSidebarCollapsedControl"] button svg,
    [data-testid="stSidebarCollapsedControl"] button span,
    button[data-testid="stExpandSidebarButton"] svg,
    button[data-testid="stExpandSidebarButton"] span,
    [data-testid="stSidebarCollapseButton"] button svg,
    [data-testid="stSidebarCollapseButton"] button span { display: none; }
    [data-testid="stSidebarCollapsedControl"] button::after {
        content: "⚙ 설정 변경"; white-space: nowrap; font-size: 14px;
    }
    button[data-testid="stExpandSidebarButton"]::after {
        content: "⚙ 설정 변경"; white-space: nowrap; font-size: 14px;
    }
    [data-testid="stSidebarCollapseButton"] button::after {
        content: "설정 닫기"; white-space: nowrap; font-size: 14px;
    }
    @media (max-width: 640px) {
        .stMainBlockContainer { padding-bottom: 6rem; }
    }
    </style>
    """)
    _settings_component()(key="settings_label", height=0)


@st.cache_resource
def _chart_component():
    # Ship the installed Plotly bundle, without an external CDN dependency.
    return components.component(
        "box_scanner_touch_chart",
        html=(_ASSETS / "chart.html").read_text(encoding="utf-8"),
        css=(_ASSETS / "chart.css").read_text(encoding="utf-8"),
        js=get_plotlyjs() + "\n" + (_ASSETS / "chart.js").read_text(encoding="utf-8"),
        isolate_styles=False,  # Plotly inserts styles into the document head.
    )


def render_chart(fig, title: str, *, key: str):
    fig.update_layout(title=None, showlegend=False, dragmode="pan",
                      margin=dict(l=48, r=14, t=12, b=35), autosize=True)
    legend = [
        {"name": trace.name, "color": trace.line.color}
        for trace in fig.data if trace.type == "scatter"
    ]
    _chart_component()(
        key=key,
        data={"figure": json.loads(fig.to_json()), "title": title, "legend": legend},
    )
