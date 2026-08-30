from __future__ import annotations

from decimal import Decimal

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
from dash import Input, Output, dcc, html

from app.components.chart_theme import apply_chart_theme
from app.components.forms import field_label, numeric_input
from app.components.kpi_card import kpi_card
from app.components.tables import data_table
from app.data.repositories import SeedRepository
from app.domain.cost_engine import mexico_today
from app.domain.display_currency import (
    format_currency,
    normalize_display_currency,
    translate_mxn,
    usd_view_note,
)
from app.domain.fx_rates import FxRateUnavailableError
from app.domain.pricing_simulator import (
    PricingSimulationInput,
    crossover_documents,
    sensitivity_series,
    simulate_pricing,
)
from app.utils.currency import format_mxn, format_percent


def layout(display_currency: str | None = "MXN"):
    currency = normalize_display_currency(display_currency)
    repo = SeedRepository()
    latest_month = repo.available_months()[-1]
    defaults = _default_inputs(repo, latest_month)
    return html.Div(
        [
            html.H1("Pricing", className="h3"),
            html.P(
                "Precio por capacidad, no por usuario. Model recurring revenue, document overage, costs, and margin.",
                className="text-muted",
            ),
            html.Section(
                [
                    html.H2("SAREMI 2026 Pricing Catalog", className="h5"),
                    html.P(
                        "Capacity-based pricing with unlimited users. Enterprise tiers are informational and "
                        "require a negotiated contract before assignment.",
                        className="text-muted",
                    ),
                    html.H3("Platform", className="h6"),
                    data_table("pricing-platform-table", _plan_rows(repo, "saremi_platform"), 10),
                    html.H3("API", className="h6 mt-4"),
                    html.P(
                        "For organizations that already have a CRM or platform and only need the processing engine.",
                        className="text-muted",
                    ),
                    data_table("pricing-api-table", _plan_rows(repo, "saremi_api"), 10),
                    html.H3("Plan crossovers", className="h6 mt-4"),
                    data_table("pricing-crossover-table", _crossover_rows(repo), 5),
                ],
                id="pricing-plans-section",
                className="mb-5",
            ),
            html.Section(
                [
                    html.H2("Pricing Simulator and Sensitivity", className="h5"),
                    html.P(
                        "Model one potential client's usage, revenue, costs, and operating margin.",
                        className="text-muted",
                    ),
                    _simulator_controls(repo, defaults),
                    html.Div(
                        id="pricing-simulation-results",
                        children=_simulation_content(defaults, currency),
                    ),
                ],
                id="pricing-simulator-section",
            ),
        ]
    )


def register_callbacks(app) -> None:
    @app.callback(
        Output("pricing-simulation-results", "children"),
        Input("pricing-plan-filter", "value"),
        Input("pricing-include-setup", "value"),
        Input("pricing-fixed-costs", "value"),
        Input("pricing-documents", "value"),
        Input("pricing-price-multiplier", "value"),
        Input("pricing-cost-multiplier", "value"),
        Input("pricing-target-margin", "value"),
        Input("display-currency-store", "data"),
    )
    def update_simulation(
        plan_id,
        include_setup,
        fixed_costs,
        documents,
        price_multiplier,
        cost_multiplier,
        target_margin,
        display_currency,
    ):
        values = {
            "plan_id": plan_id,
            "include_setup": include_setup,
            "fixed_costs": fixed_costs,
            "documents": documents,
            "validations": 0,
            "graph_queries": 0,
            "blockchain_transactions": 0,
            "folios": 0,
            "price_multiplier": price_multiplier,
            "cost_multiplier": cost_multiplier,
            "target_margin": target_margin,
        }
        try:
            return _simulation_content(values, display_currency)
        except FxRateUnavailableError as exc:
            return dbc.Alert(str(exc), color="danger")


def _simulator_controls(repo: SeedRepository, defaults: dict):
    return dbc.Card(
        dbc.CardBody(
            [
                html.H3("Simulation Inputs", className="h6"),
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                field_label(
                                    "Pricing plan",
                                    "pricing-plan-filter",
                                    "Plan template used to auto-fill fixed fees, included usage, and unit prices.",
                                ),
                                dcc.Dropdown(
                                    id="pricing-plan-filter",
                                    options=[
                                        {"label": plan.name, "value": plan.id}
                                        for plan in repo.pricing_plans(catalog_only=True, assignable_only=True)
                                    ],
                                    value=defaults["plan_id"],
                                    clearable=False,
                                    persistence=True,
                                    persistence_type="session",
                                ),
                            ],
                            md=3,
                        ),
                        dbc.Col(
                            [
                                field_label(
                                    "Setup fee",
                                    "pricing-include-setup",
                                    "Include the one-time setup fee in this client example.",
                                ),
                                dbc.Checklist(
                                    id="pricing-include-setup",
                                    options=[{"label": "Include setup fee", "value": "include"}],
                                    value=["include"],
                                    switch=True,
                                    persistence=True,
                                    persistence_type="session",
                                ),
                            ],
                            md=3,
                        ),
                        numeric_input(
                            "Allocated fixed costs",
                            "pricing-fixed-costs",
                            defaults["fixed_costs"],
                            tooltip="Share of monthly fixed costs assigned to this potential client.",
                        ),
                        numeric_input(
                            "Target unit margin",
                            "pricing-target-margin",
                            defaults["target_margin"],
                            0.05,
                            "Target margin used to calculate the minimum document price.",
                        ),
                    ],
                    className="g-3 mb-3",
                ),
                dbc.Row(
                    [
                        numeric_input(
                            "Documents",
                            "pricing-documents",
                            defaults["documents"],
                            tooltip="Expected documents processed for this client in one month.",
                        ),
                        numeric_input(
                            "Price multiplier",
                            "pricing-price-multiplier",
                            defaults["price_multiplier"],
                            0.05,
                            "Multiplier applied to all variable unit prices. Use 1.20 for +20% prices.",
                        ),
                        numeric_input(
                            "Cost multiplier",
                            "pricing-cost-multiplier",
                            defaults["cost_multiplier"],
                            0.05,
                            "Multiplier applied to all variable unit costs. Use 1.20 for +20% costs.",
                        ),
                    ],
                    className="g-3",
                ),
            ]
        ),
        className="content-card mb-3",
    )


def _simulation_content(values: dict, display_currency: str | None = "MXN"):
    currency = normalize_display_currency(display_currency)
    simulation_input = _simulation_input(values)
    result = simulate_pricing(simulation_input)
    sensitivity = sensitivity_series(
        simulation_input,
        usage_multipliers=[Decimal("0.50"), Decimal("1.00"), Decimal("1.50"), Decimal("2.00")],
        price_multipliers=[Decimal("0.80"), Decimal("1.00"), Decimal("1.20")],
    )
    rate = None
    if currency == "USD":
        recognition_date = mexico_today()
        rate = SeedRepository().usd_mxn_rates_for_dates([recognition_date])[recognition_date]

    def presented(value):
        return translate_mxn(value, currency, rate)

    return html.Div(
        [
            usd_view_note(currency),
            dbc.Row(
                [
                    dbc.Col(
                        kpi_card(
                            "Client Revenue",
                            format_currency(presented(result.revenue), currency),
                            "Plan pricing auto-filled from selected plan",
                            tooltip="Total revenue expected from one client: setup fee, monthly fixed fee, and any "
                            "usage billed above the plan's included limits.",
                        ),
                        md=3,
                    ),
                    dbc.Col(
                        kpi_card(
                            "Client Costs",
                            format_currency(presented(result.total_cost), currency),
                            f"{format_currency(presented(result.variable_cost), currency)} variable",
                            color="warning",
                            tooltip="Total cost assigned to this client: allocated fixed costs plus usage-based "
                            "variable costs.",
                        ),
                        md=3,
                    ),
                    dbc.Col(
                        kpi_card(
                            "Operating Margin",
                            format_currency(presented(result.operating_margin), currency),
                            format_percent(result.operating_margin_percentage),
                            color="success" if result.operating_margin >= 0 else "danger",
                            tooltip="Profit or loss from this client after both variable costs and allocated fixed "
                            "costs.",
                        ),
                        md=3,
                    ),
                    dbc.Col(
                        kpi_card(
                            "Recurring Revenue / Doc",
                            (
                                format_currency(presented(result.recurring_revenue_per_document), currency, decimals=2)
                                if result.recurring_revenue_per_document is not None
                                else "n/a"
                            ),
                            "Monthly fee + overage, excluding setup",
                            tooltip="Implicit recurring revenue divided by the hypothetical processed documents.",
                        ),
                        md=3,
                    ),
                ],
                className="g-3 mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(dcc.Graph(figure=_sensitivity_chart(sensitivity, currency, rate)), md=7),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H2("Revenue and Cost Split", className="h5"),
                                    data_table("pricing-split-table", _split_rows(result), 7),
                                ]
                            ),
                            className="content-card h-100",
                        ),
                        md=5,
                    ),
                ],
                className="mb-4",
            ),
            html.H2("Usage and Price Sensitivity", className="h5"),
            data_table("pricing-sensitivity-table", _sensitivity_rows(sensitivity), 8),
        ]
    )


def _simulation_input(values: dict) -> PricingSimulationInput:
    repo = SeedRepository()
    plan = _plan_by_id(repo, int(_number(values.get("plan_id"), 8)))
    rates = repo.cost_rates()
    include_setup = "include" in (values.get("include_setup") or [])
    return PricingSimulationInput(
        pricing_plan=plan,
        clients=1,
        onboarding_clients=1 if include_setup else 0,
        documents_per_client=_number(values.get("documents"), 0),
        validations_per_client=_number(values.get("validations"), 0),
        graph_queries_per_client=_number(values.get("graph_queries"), 0),
        blockchain_transactions_per_client=_number(values.get("blockchain_transactions"), 0),
        folios_per_client=_number(values.get("folios"), 0),
        fixed_costs=_number(values.get("fixed_costs"), 0),
        document_unit_cost=rates.get("saremi.document_validation", Decimal("0")),
        validation_unit_cost=rates.get("saremi.validation", Decimal("0")),
        graph_query_unit_cost=rates.get("graphos.query", Decimal("0")),
        blockchain_transaction_unit_cost=rates.get("blockchain.asiento_registration", Decimal("0")),
        folio_unit_cost=rates.get("blockchain.folio_mint", Decimal("0")),
        price_multiplier=_number(values.get("price_multiplier"), 1),
        variable_cost_multiplier=_number(values.get("cost_multiplier"), 1),
        target_unit_margin=_number(values.get("target_margin"), Decimal("0.60")),
    )


def _default_inputs(repo: SeedRepository, month: str) -> dict:
    active_clients = repo.active_clients(month)
    client_count = max(len(active_clients), 1)
    usage = repo.usage_for_month(month)
    return {
        "plan_id": next(
            (plan.id for plan in repo.pricing_plans(catalog_only=True, assignable_only=True) if plan.featured),
            7,
        ),
        "include_setup": ["include"],
        "fixed_costs": repo.monthly_summary(month)["fixed_cost"] / Decimal(client_count),
        "documents": _average_usage(usage, "saremi.document_validation", client_count),
        "validations": _average_usage(usage, "saremi.ine_validation", client_count),
        "graph_queries": _average_usage(usage, "graphos.query", client_count),
        "blockchain_transactions": _average_usage(usage, "blockchain.asiento_registration", client_count),
        "folios": _average_usage(usage, "blockchain.folio_mint", client_count),
        "price_multiplier": 1,
        "cost_multiplier": 1,
        "target_margin": 0.6,
    }


def _sensitivity_chart(rows: list[dict], display_currency: str = "MXN", rate=None):
    currency = normalize_display_currency(display_currency)
    df = pd.DataFrame(
        [
            {
                "price_case": row["price_case"],
                "usage_multiplier": row["usage_multiplier"],
                "operating_margin": float(translate_mxn(row["operating_margin"], currency, rate)),
            }
            for row in rows
        ]
    )
    fig = px.line(
        df,
        x="usage_multiplier",
        y="operating_margin",
        color="price_case",
        markers=True,
        title="Operating Margin Sensitivity",
    )
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20), xaxis_title="Usage multiplier", legend_title="")
    fig.update_yaxes(title=currency, tickprefix="$", separatethousands=True)
    fig.update_traces(hovertemplate=f"%{{x}}<br>$%{{y:,.2f}} {currency}<extra></extra>")
    return apply_chart_theme(fig)


def _split_rows(result) -> list[dict]:
    return [
        {"item": "Setup fee", "amount": format_mxn(result.setup_revenue)},
        {"item": "Monthly fixed fee", "amount": format_mxn(result.subscription_revenue)},
        {"item": "Billable usage revenue", "amount": format_mxn(result.usage_revenue)},
        {"item": "Variable costs", "amount": format_mxn(result.variable_cost)},
        {"item": "Allocated fixed costs", "amount": format_mxn(result.fixed_cost)},
        {"item": "Total costs", "amount": format_mxn(result.total_cost)},
        {"item": "Operating margin", "amount": format_mxn(result.operating_margin)},
    ]


def _sensitivity_rows(rows: list[dict]) -> list[dict]:
    return [
        {
            "price_case": row["price_case"],
            "usage_multiplier": f"{row['usage_multiplier']:.0%}",
            "revenue": format_mxn(row["revenue"]),
            "total_cost": format_mxn(row["total_cost"]),
            "operating_margin": format_mxn(row["operating_margin"]),
        }
        for row in rows
    ]


def _average_usage(usage_events, event_type: str, client_count: int) -> float:
    total = sum(float(event.quantity) for event in usage_events if event.event_type == event_type)
    return round(total / client_count, 2)


def _plan_rows(repo: SeedRepository, service_line: str) -> list[dict]:
    return [
        {
            "plan": f"{plan.name}{' ★ ' + plan.featured_label if plan.featured else ''}",
            "status": "Available" if plan.assignable else "Contact sales",
            "monthly_fee": _format_catalog_money(plan.monthly_fixed_fee),
            "included_documents": _format_catalog_quantity(plan.included_documents),
            "overage_per_document": _format_catalog_money(plan.price_per_document, decimals=2),
            "setup": _setup_label(plan),
            "users": "Unlimited" if plan.unlimited_users and service_line == "saremi_platform" else "API access",
            "processing": plan.processing_description or "Custom",
            "configuration": plan.configuration_description or "Custom",
            "support": plan.support_description or "Custom",
        }
        for plan in repo.pricing_plans(catalog_only=True, service_line=service_line)
    ]


def _plan_by_id(repo: SeedRepository, plan_id: int):
    plans = repo.pricing_plans(catalog_only=True, assignable_only=True)
    selected = next((plan for plan in plans if plan.id == plan_id), None)
    if selected is not None:
        return selected
    featured = next((plan for plan in plans if plan.featured), None)
    if featured is not None:
        return featured
    if not plans:
        raise ValueError("No active assignable pricing plans are available.")
    return plans[0]


def _number(value, default) -> Decimal:
    if value is None or value == "":
        return Decimal(str(default))
    return Decimal(str(value))


def _format_catalog_money(value: Decimal | float | int | None, *, decimals: int = 0) -> str:
    if value is None:
        return "A la medida"
    return f"${float(value):,.{decimals}f} MXN"


def _format_catalog_quantity(value: int | None) -> str:
    return f"{value:,}" if value is not None else "According to operation"


def _setup_label(plan) -> str:
    if plan.setup_fee is None:
        return "A la medida"
    if plan.setup_fee == 0:
        return "Included / $0" if plan.setup_type == "included" else "Not applicable / $0"
    minimum = f" (minimum {_format_catalog_money(plan.minimum_setup_fee)})" if plan.minimum_setup_fee else ""
    return f"{_format_catalog_money(plan.setup_fee)}{minimum}"


def _crossover_rows(repo: SeedRepository) -> list[dict]:
    plans = {plan.plan_code: plan for plan in repo.pricing_plans(catalog_only=True)}
    pairs = [
        ("SAREMI_CORE", "SAREMI_SCALE", "Review sustained use near 1,400–1,500"),
        ("SAREMI_API_1K", "SAREMI_API_2_5K", "Consider the next API tier"),
        ("SAREMI_API_2_5K", "SAREMI_API_10K", "Subject to infrastructure validation"),
    ]
    return [
        {
            "from": plans[current].name,
            "to": plans[next_plan].name,
            "crossover_documents": crossover_documents(plans[current], plans[next_plan]),
            "guidance": guidance,
        }
        for current, next_plan, guidance in pairs
        if current in plans and next_plan in plans
    ]
