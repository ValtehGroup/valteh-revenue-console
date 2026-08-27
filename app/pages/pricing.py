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
from app.domain.pricing_simulator import PricingSimulationInput, sensitivity_series, simulate_pricing
from app.utils.currency import format_mxn, format_percent


def layout():
    repo = SeedRepository()
    latest_month = repo.available_months()[-1]
    defaults = _default_inputs(repo, latest_month)
    return html.Div(
        [
            html.H1("Pricing", className="h3"),
            html.P(
                "Review Valteh's pricing plans, then model revenue, costs, and margin sensitivity.",
                className="text-muted",
            ),
            html.Section(
                [
                    html.H2("Pricing Plans", className="h5"),
                    html.P(
                        "Compare the fixed fees, included usage, and unit pricing of each available plan.",
                        className="text-muted",
                    ),
                    data_table("pricing-table", _plan_rows(repo), 10),
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
                    html.Div(id="pricing-simulation-results", children=_simulation_content(defaults)),
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
        Input("pricing-validations", "value"),
        Input("pricing-graph-queries", "value"),
        Input("pricing-blockchain-transactions", "value"),
        Input("pricing-folios", "value"),
        Input("pricing-price-multiplier", "value"),
        Input("pricing-cost-multiplier", "value"),
        Input("pricing-target-margin", "value"),
    )
    def update_simulation(
        plan_id,
        include_setup,
        fixed_costs,
        documents,
        validations,
        graph_queries,
        blockchain_transactions,
        folios,
        price_multiplier,
        cost_multiplier,
        target_margin,
    ):
        values = {
            "plan_id": plan_id,
            "include_setup": include_setup,
            "fixed_costs": fixed_costs,
            "documents": documents,
            "validations": validations,
            "graph_queries": graph_queries,
            "blockchain_transactions": blockchain_transactions,
            "folios": folios,
            "price_multiplier": price_multiplier,
            "cost_multiplier": cost_multiplier,
            "target_margin": target_margin,
        }
        return _simulation_content(values)


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
                                    options=[{"label": plan.name, "value": plan.id} for plan in repo.pricing_plans()],
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
                            "ID validations",
                            "pricing-validations",
                            defaults["validations"],
                            tooltip="Expected ID validation events for this client in one month.",
                        ),
                        numeric_input(
                            "Graph queries",
                            "pricing-graph-queries",
                            defaults["graph_queries"],
                            tooltip="Expected Graphos queries for this client in one month.",
                        ),
                        numeric_input(
                            "Blockchain tx",
                            "pricing-blockchain-transactions",
                            defaults["blockchain_transactions"],
                            tooltip="Expected blockchain audit or registry events for this client in one month.",
                        ),
                    ],
                    className="g-3 mb-3",
                ),
                dbc.Row(
                    [
                        numeric_input(
                            "Folios minted",
                            "pricing-folios",
                            defaults["folios"],
                            tooltip="Expected property folios or mints for this client in one month.",
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


def _simulation_content(values: dict):
    simulation_input = _simulation_input(values)
    result = simulate_pricing(simulation_input)
    sensitivity = sensitivity_series(
        simulation_input,
        usage_multipliers=[Decimal("0.50"), Decimal("1.00"), Decimal("1.50"), Decimal("2.00")],
        price_multipliers=[Decimal("0.80"), Decimal("1.00"), Decimal("1.20")],
    )
    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        kpi_card(
                            "Client Revenue",
                            format_mxn(result.revenue),
                            "Plan pricing auto-filled from selected plan",
                            tooltip="Total revenue expected from one client: setup fee, monthly fixed fee, and any "
                            "usage billed above the plan's included limits.",
                        ),
                        md=3,
                    ),
                    dbc.Col(
                        kpi_card(
                            "Client Costs",
                            format_mxn(result.total_cost),
                            f"{format_mxn(result.variable_cost)} variable",
                            color="warning",
                            tooltip="Total cost assigned to this client: allocated fixed costs plus usage-based "
                            "variable costs.",
                        ),
                        md=3,
                    ),
                    dbc.Col(
                        kpi_card(
                            "Operating Margin",
                            format_mxn(result.operating_margin),
                            format_percent(result.operating_margin_percentage),
                            color="success" if result.operating_margin >= 0 else "danger",
                            tooltip="Profit or loss from this client after both variable costs and allocated fixed "
                            "costs.",
                        ),
                        md=3,
                    ),
                    dbc.Col(
                        kpi_card(
                            "Minimum Doc Price",
                            _format_mxn_2(result.minimum_document_price),
                            "For target unit margin",
                            tooltip="Minimum price per document needed to reach the selected target unit margin, "
                            "based on current document cost.",
                        ),
                        md=3,
                    ),
                ],
                className="g-3 mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(dcc.Graph(figure=_sensitivity_chart(sensitivity)), md=7),
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
    plan = _plan_by_id(repo, int(_number(values.get("plan_id"), 2)))
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
        "plan_id": 2,
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


def _sensitivity_chart(rows: list[dict]):
    df = pd.DataFrame(
        [
            {
                "price_case": row["price_case"],
                "usage_multiplier": row["usage_multiplier"],
                "operating_margin": float(row["operating_margin"]),
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
    fig.update_yaxes(title="MXN", tickprefix="$", separatethousands=True)
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


def _plan_rows(repo: SeedRepository) -> list[dict]:
    return [
        {
            "plan": plan.name,
            "setup_fee": format_mxn(plan.setup_fee),
            "annual_fee": format_mxn(plan.annual_fee),
            "monthly_fixed_fee": format_mxn(plan.monthly_fixed_fee),
            "included_documents": plan.included_documents,
            "included_validations": plan.included_validations,
            "included_graph_queries": plan.included_graph_queries,
            "included_blockchain_transactions": plan.included_blockchain_transactions,
            "price_per_document": _format_mxn_2(plan.price_per_document),
            "price_per_validation": _format_mxn_2(plan.price_per_validation),
            "price_per_graph_query": _format_mxn_2(plan.price_per_graph_query),
            "price_per_blockchain_transaction": _format_mxn_2(plan.price_per_blockchain_transaction),
            "price_per_property_mint": _format_mxn_2(plan.price_per_property_mint),
            "revenue_share_percentage": f"{float(plan.revenue_share_percentage) * 100:.1f}%",
        }
        for plan in repo.pricing_plans()
    ]


def _plan_by_id(repo: SeedRepository, plan_id: int):
    return next(plan for plan in repo.pricing_plans() if plan.id == plan_id)


def _number(value, default) -> Decimal:
    if value is None or value == "":
        return Decimal(str(default))
    return Decimal(str(value))


def _format_mxn_2(value: Decimal | float | int) -> str:
    return f"${float(value):,.2f} MXN"
