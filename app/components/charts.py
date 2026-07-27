from decimal import Decimal

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from app.components.chart_theme import DEFAULT_PLOTLY_COLORWAY, apply_chart_theme


def bar_chart(data: dict[str, Decimal], title: str, *, default_plotly_colors: bool = False) -> go.Figure:
    df = pd.DataFrame({"label": list(data.keys()), "value": [float(v) for v in data.values()]})
    colorway = DEFAULT_PLOTLY_COLORWAY if default_plotly_colors else None
    fig = px.bar(
        df,
        x="label",
        y="value",
        title=title,
        text_auto=".2s",
        color_discrete_sequence=colorway,
    )
    fig.update_layout(yaxis_title="MXN", xaxis_title="")
    return apply_chart_theme(fig, colorway=colorway)


def line_chart(df: pd.DataFrame, x: str, y: str, title: str) -> go.Figure:
    fig = px.line(df, x=x, y=y, markers=True, title=title)
    return apply_chart_theme(fig)


def pie_chart(data: dict[str, Decimal], title: str, *, default_plotly_colors: bool = False) -> go.Figure:
    colorway = DEFAULT_PLOTLY_COLORWAY if default_plotly_colors else None
    fig = px.pie(
        names=list(data.keys()),
        values=[float(v) for v in data.values()],
        title=title,
        hole=0.45,
        color_discrete_sequence=colorway,
    )
    return apply_chart_theme(fig, colorway=colorway)
