from decimal import Decimal

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from app.components.chart_theme import apply_chart_theme


def bar_chart(data: dict[str, Decimal], title: str) -> go.Figure:
    df = pd.DataFrame({"label": list(data.keys()), "value": [float(v) for v in data.values()]})
    fig = px.bar(df, x="label", y="value", title=title, text_auto=".2s")
    fig.update_layout(yaxis_title="MXN", xaxis_title="")
    return apply_chart_theme(fig)


def line_chart(df: pd.DataFrame, x: str, y: str, title: str) -> go.Figure:
    fig = px.line(df, x=x, y=y, markers=True, title=title)
    return apply_chart_theme(fig)


def pie_chart(data: dict[str, Decimal], title: str) -> go.Figure:
    fig = px.pie(names=list(data.keys()), values=[float(v) for v in data.values()], title=title, hole=0.45)
    return apply_chart_theme(fig)
