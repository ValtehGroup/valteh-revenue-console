from decimal import Decimal

from app.layout import NAV_ITEMS
from app.pages.executive_dashboard import (
    _executive_bar_chart,
    _executive_pie_chart,
    _format_mxn_thousands,
    layout,
)


def test_executive_dashboard_is_renamed_to_executive_summary() -> None:
    assert NAV_ITEMS[0] == ("Executive Summary", "/")
    assert "Executive Summary" in str(layout())
    assert "Executive Dashboard" not in str(layout())


def test_executive_bar_chart_uses_compact_mxn_hover_and_grouped_axis() -> None:
    figure = _executive_bar_chart({"SAREMI": Decimal("1555")}, "Revenue")

    assert figure.data[0].hovertemplate == "%{x}<br>%{customdata}<extra></extra>"
    assert list(figure.data[0].customdata) == ["$1.6k MXN"]
    assert figure.layout.yaxis.tickformat == ",.0f"


def test_executive_pie_chart_uses_compact_mxn_hover() -> None:
    figure = _executive_pie_chart({"SAREMI": Decimal("1555")}, "Revenue")

    assert figure.data[0].hovertemplate == "%{label}<br>%{customdata}<extra></extra>"
    assert list(figure.data[0].customdata) == ["$1.6k MXN"]


def test_mxn_hover_format_keeps_one_decimal_in_thousands() -> None:
    assert _format_mxn_thousands(Decimal("1000")) == "1.0k MXN"
    assert _format_mxn_thousands(Decimal("1555")) == "1.6k MXN"
