import dash_bootstrap_components as dbc
from dash import html


def kpi_card(
    title: str,
    value: str,
    subtitle: str | None = None,
    color: str = "primary",
    tooltip: str | None = None,
    card_id: str | None = None,
) -> html.Div:
    target_id = card_id or f"kpi-{_slugify(title)}"
    tooltip_id = f"{target_id}-tooltip"
    card = dbc.Card(
        dbc.CardBody(
            [
                html.Div(title, className="kpi-label"),
                html.Div(value, className=f"kpi-value kpi-value--{color}"),
                html.Div(subtitle or "", className="kpi-subtitle"),
            ]
        ),
        className="kpi-card h-100",
    )
    children = [card]
    if tooltip:
        children.append(html.Div(tooltip, className="kpi-tooltip", id=tooltip_id, role="tooltip"))
    return html.Div(
        children,
        className="kpi-card-wrapper h-100",
        id=target_id,
        tabIndex=0 if tooltip else None,
        **({"aria-describedby": tooltip_id} if tooltip else {}),
    )


def _slugify(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "-" for character in value).strip("-")
