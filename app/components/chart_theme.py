from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
from flask import has_request_context, request

FONT_FAMILY = '"Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif'
DEFAULT_PLOTLY_COLORWAY = list(px.colors.qualitative.Plotly)

PLOTLY_THEME = {
    "light": {
        "text": "#1E293B",
        "muted": "#5F574B",
        "grid": "#E7E2D8",
        "axis": "#8B8172",
        "hover_bg": "#FFFFFF",
        "hover_border": "#D8D3C8",
        "colorway": ["#0F766E", "#6B1F2E", "#B8924A", "#134E4A", "#8B7E6B", "#2563EB"],
    },
    "dark": {
        "text": "#F8FAFC",
        "muted": "#A8B3C4",
        "grid": "#293548",
        "axis": "#64748B",
        "hover_bg": "#1D293D",
        "hover_border": "#64748B",
        "colorway": ["#00B4B4", "#60A5FA", "#34D399", "#FBBF24", "#EF4444", "#A78BFA"],
    },
}


def chart_colorway(theme: str | None = None) -> list[str]:
    return list(PLOTLY_THEME[_resolved_theme(theme)]["colorway"])


def plotly_template(theme: str | None = None, colorway: list[str] | None = None) -> go.layout.Template:
    colors = PLOTLY_THEME[_resolved_theme(theme)]
    axis = {
        "automargin": True,
        "color": colors["muted"],
        "gridcolor": colors["grid"],
        "linecolor": colors["axis"],
        "showline": False,
        "tickcolor": colors["axis"],
        "title": {"font": {"color": colors["muted"], "size": 12}},
        "zerolinecolor": colors["axis"],
    }
    return go.layout.Template(
        layout={
            "autosize": True,
            "colorway": colorway if colorway is not None else colors["colorway"],
            "font": {"color": colors["text"], "family": FONT_FAMILY, "size": 13},
            "hoverlabel": {
                "bgcolor": colors["hover_bg"],
                "bordercolor": colors["hover_border"],
                "font": {"color": colors["text"], "family": FONT_FAMILY, "size": 13},
            },
            "legend": {
                "bgcolor": "rgba(0,0,0,0)",
                "font": {"color": colors["muted"], "family": FONT_FAMILY, "size": 12},
                "title": {"font": {"color": colors["muted"], "family": FONT_FAMILY, "size": 12}},
            },
            "margin": {"l": 24, "r": 16, "t": 52, "b": 28},
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
            "title": {
                "font": {"color": colors["text"], "family": FONT_FAMILY, "size": 17},
                "x": 0.01,
                "xanchor": "left",
            },
            "xaxis": axis,
            "yaxis": axis,
        }
    )


def apply_chart_theme(
    figure: go.Figure,
    theme: str | None = None,
    colorway: list[str] | None = None,
) -> go.Figure:
    figure.update_layout(template=plotly_template(theme, colorway))
    return figure


def _resolved_theme(theme: str | None) -> str:
    if theme is not None:
        return theme if theme in PLOTLY_THEME else "light"
    if has_request_context():
        cookie_theme = request.cookies.get("valteh-theme")
        if cookie_theme in PLOTLY_THEME:
            return cookie_theme
    return "light"
