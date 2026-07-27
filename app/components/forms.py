import dash_bootstrap_components as dbc
from dash import html


def numeric_input(
    label: str,
    component_id: str,
    value: float,
    step: float = 1.0,
    tooltip: str | None = None,
) -> dbc.Col:
    return dbc.Col(
        [
            field_label(label, component_id, tooltip),
            dbc.Input(
                id=component_id,
                type="number",
                value=value,
                step=step,
                persistence=True,
                persistence_type="session",
            ),
        ],
        md=3,
    )


def field_label(label: str, component_id: str, tooltip: str | None = None) -> html.Div:
    if not tooltip:
        return html.Label(label, className="form-label", htmlFor=component_id)
    tooltip_id = f"{component_id}-info-tooltip"
    return html.Div(
        [
            html.Label(label, className="form-label mb-0", htmlFor=component_id),
            html.Span(
                [
                    html.Span(
                        "i",
                        className="field-info-icon",
                        **{"aria-hidden": "true"},
                    ),
                    html.Span(tooltip, className="field-tooltip", id=tooltip_id, role="tooltip"),
                ],
                className="field-info-wrapper",
                tabIndex=0,
                **{"aria-label": f"Information about {label}"},
                **{"aria-describedby": tooltip_id},
            ),
        ],
        className="field-label-row",
    )
