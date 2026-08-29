from dataclasses import replace
from datetime import date
from decimal import Decimal

from dash import dcc

from app.components.chart_theme import DEFAULT_PLOTLY_COLORWAY
from app.components.tables import data_table
from app.data.repositories import SeedRepository
from app.domain.cost_engine import CostAmount
from app.domain.fx_rates import ResolvedFxRate
from app.main import create_app
from app.pages.costs import (
    _action_form,
    _catalog_rows,
    _cost_table_styles,
    _cost_type_for_frequency,
    _month_options,
    _monthly_cost_rows,
    _selected_cost,
    _summarize_cost_rows,
    _year_cost_chart,
)


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        yield from _walk(child)


def _cost_row(month: str, fixed: str, variable: str, one_time: str = "0") -> dict:
    fixed_amount = Decimal(fixed)
    variable_amount = Decimal(variable)
    one_time_amount = Decimal(one_time)
    return {
        "month": month,
        "fixed": fixed_amount,
        "variable": variable_amount,
        "one_time": one_time_amount,
        "total": fixed_amount + variable_amount + one_time_amount,
    }


def test_cost_summary_reconciles_fixed_variable_and_one_time_costs() -> None:
    split = _summarize_cost_rows(
        [
            _cost_row("2026-01", "100", "20", "50"),
            _cost_row("2026-02", "120", "30"),
        ]
    )

    assert split == {
        "fixed": Decimal("270"),
        "variable": Decimal("50"),
        "total": Decimal("320"),
    }


def test_monthly_cost_table_exposes_one_fx_reference_for_usd_and_mxn_costs() -> None:
    amount = CostAmount(
        cost_key="software.usd",
        name="USD subscription",
        provider="Provider",
        category="Software",
        service_line="Shared",
        cost_type="fixed",
        charge_basis="flat",
        quantity=Decimal("1"),
        unit_cost=Decimal("10"),
        currency="USD",
        unit="month",
        billing_frequency="monthly",
        start_date=date(2026, 1, 1),
        end_date=None,
        record_type="actual",
        amount=Decimal("170.43"),
        source_unit_cost=Decimal("10"),
        source_currency="USD",
        fx_rate=Decimal("17.0427"),
        valuation_date=date(2026, 8, 29),
        fx_rate_date=date(2026, 8, 28),
        provisional_fx=True,
    )
    mxn_amount = replace(
        amount,
        cost_key="software.mxn",
        name="MXN subscription",
        unit_cost=Decimal("100"),
        currency="MXN",
        amount=Decimal("100"),
        source_unit_cost=Decimal("100"),
        source_currency="MXN",
        fx_rate=None,
        fx_rate_date=None,
        provisional_fx=False,
    )

    class Repository:
        @staticmethod
        def monthly_cost_amounts(_month: str):
            return [amount, mxn_amount]

        @staticmethod
        def usd_mxn_rates_for_dates(_dates):
            return {date(2026, 8, 29): ResolvedFxRate("USD", date(2026, 8, 29), Decimal("17.0427"), date(2026, 8, 28))}

    rows = _monthly_cost_rows(Repository(), "2026-08")

    assert [row["usd_mxn_used"] for row in rows] == ["17.0427", "17.0427"]
    assert all({"fx_rate", "fx_date", "valuation_date", "fx_status"}.isdisjoint(row) for row in rows)


def test_year_chart_stacks_fixed_and_variable_monthly_costs() -> None:
    figure = _year_cost_chart(
        [
            _cost_row("2026-01", "100", "20", "50"),
            _cost_row("2026-02", "120", "30"),
        ],
        2026,
    )

    traces = {trace.name: list(trace.y) for trace in figure.data}
    assert traces == {
        "Fixed + one-time": [150.0, 120.0],
        "Variable": [20.0, 30.0],
    }
    assert figure.layout.xaxis.type == "category"
    assert figure.layout.xaxis.tickformat == "%Y-%m"
    assert all("%{fullData.name}" in trace.hovertemplate for trace in figure.data)
    assert [trace.marker.color for trace in figure.data] == DEFAULT_PLOTLY_COLORWAY[:2]
    assert list(figure.layout.template.layout.colorway) == DEFAULT_PLOTLY_COLORWAY


def test_month_options_are_limited_to_selected_available_year() -> None:
    options = _month_options(["2025-12", "2026-01", "2026-02"], "2026")

    assert options == [
        {"label": "January", "value": "2026-01"},
        {"label": "February", "value": "2026-02"},
    ]


def test_cost_form_offers_only_actual_and_estimate_record_types() -> None:
    form = _action_form("add", None)
    record_type = next(
        component
        for component in _walk(form)
        if isinstance(component, dcc.Dropdown) and component.id == {"type": "cost-field", "name": "record_type"}
    )

    assert [option["value"] for option in record_type.options] == ["actual", "estimate"]


def test_cost_type_is_derived_from_billing_frequency() -> None:
    assert _cost_type_for_frequency("usage") == "variable"
    assert _cost_type_for_frequency("monthly") == "fixed"
    assert _cost_type_for_frequency("annual") == "fixed"
    assert _cost_type_for_frequency("once") == "fixed"


def test_management_table_includes_ids_status_and_audit_timestamps() -> None:
    repo = SeedRepository()
    rows = _catalog_rows(repo)

    assert rows
    assert {
        "id",
        "status",
        "base_amount",
        "created_at",
        "updated_at",
        "updated_at_raw",
    } <= rows[0].keys()
    assert rows[0]["created_at"].endswith(" UTC")
    assert rows[0]["updated_at"].endswith(" UTC")
    assert len(rows[0]["id"]) >= 4
    assert rows[0]["quantity"].replace(",", "").isdigit()
    assert len(rows[0]["unit_cost"].split(".")[-1]) == 2
    rows_by_id = {row["id"]: row for row in rows}
    for item in repo.cost_items():
        assert rows_by_id[f"{item.id:04d}"]["base_amount"] == (
            f"${item.entered_configured_amount:,.2f} {item.display_currency}"
        )
    assert {"usd_mxn_used", "fx_rate", "fx_date", "valuation_date", "fx_status"}.isdisjoint(rows[0])
    assert all(row["status"] == row["status"].lower() for row in rows)


def test_management_table_prioritizes_operational_columns() -> None:
    row = _catalog_rows(SeedRepository())[0]
    visible_columns = [column for column in row if column not in {"cost_key", "created_at", "updated_at_raw"}]

    assert visible_columns == [
        "id",
        "name",
        "status",
        "category",
        "service_line",
        "provider",
        "cost_type",
        "frequency",
        "charge_basis",
        "quantity",
        "unit",
        "unit_cost",
        "currency",
        "base_amount",
        "start_date",
        "end_date",
        "record_type",
        "updated_at",
        "notes",
    ]


def test_selected_cost_resolves_by_stable_row_id() -> None:
    rows = [{"id": "0010", "name": "First"}, {"id": "0020", "name": "Second"}]

    assert _selected_cost("0020", rows) == rows[1]
    assert _selected_cost(None, rows) is None


def test_selected_cost_row_gets_theme_safe_full_row_highlight() -> None:
    styles = _cost_table_styles("0020")
    selected_row_style = next(style for style in styles if style["if"].get("filter_query") == '{id} = "0020"')

    assert selected_row_style["backgroundColor"] == "var(--color-surface-soft)"
    assert selected_row_style["color"] == "var(--color-text)"
    assert selected_row_style["borderTop"] == "2px solid var(--color-primary)"


def test_cost_status_cells_use_saremi_status_colors() -> None:
    styles = _cost_table_styles(None)

    active = next(style for style in styles if style["if"].get("filter_query") == '{status} = "active"')
    inactive = next(style for style in styles if style["if"].get("filter_query") == '{status} = "inactive"')

    assert active["color"] == "var(--color-status-active)"
    assert inactive["color"] == "var(--color-danger)"


def test_internal_cost_fields_are_excluded_from_rendered_columns() -> None:
    table = data_table(
        "test-costs-table",
        [{"id": 1, "cost_key": "internal.key", "name": "Visible", "updated_at_raw": "internal"}],
        excluded_columns=["cost_key", "updated_at_raw"],
    )
    props = table.to_plotly_json()["props"]

    assert [column["id"] for column in props["columns"]] == ["id", "name"]
    assert "hidden_columns" not in props


def test_base_amount_column_uses_plain_label_with_currency_in_value() -> None:
    table = data_table("test-costs-table", [{"base_amount": "$123.45 USD"}])

    assert table.to_plotly_json()["props"]["columns"] == [{"name": "Base Amount", "id": "base_amount"}]


def test_success_refresh_signal_updates_management_table_and_dashboard() -> None:
    app = create_app()
    refresh_consumers = {
        callback_key
        for callback_key, callback in app.callback_map.items()
        if any(item["id"] == "costs-refresh" for item in callback["inputs"])
    }

    assert any("costs-table.data" in key for key in refresh_consumers)
    assert any("costs-dashboard-content.children" in key for key in refresh_consumers)
    assert any("costs-month-filter.options" in key for key in refresh_consumers)
    assert any("costs-selected-row-id.data" in key for key in app.callback_map)
    assert all("delete" not in key.lower() for key in app.callback_map)
