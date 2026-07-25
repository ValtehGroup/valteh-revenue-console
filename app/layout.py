import dash_bootstrap_components as dbc
from dash import dcc, html

NAV_ITEMS = [
    ("Executive Dashboard", "/"),
    ("Clients", "/clients"),
    ("Costs", "/costs"),
    ("Pricing", "/pricing"),
    ("Usage", "/usage"),
    ("Scenarios", "/scenarios"),
]


def app_layout() -> html.Div:
    sidebar = html.Nav(
        [
            html.Div(
                [
                    html.Img(
                        src="/assets/valteh_logo_Blue_Vertical.png",
                        alt="Valteh logo",
                        className="brand-logo",
                    ),
                    html.Div(
                        [
                            html.Div("Valteh", className="h4 mb-0"),
                            html.Div("Economics Dashboard", className="text-muted small"),
                        ]
                    ),
                ],
                className="brand-header mb-4",
            ),
            dbc.Nav(
                [dbc.NavLink(label, href=href, active="exact") for label, href in NAV_ITEMS],
                vertical=True,
                pills=True,
            ),
        ],
        className="sidebar bg-white border-end p-4",
    )
    return html.Div(
        [
            dcc.Location(id="url"),
            sidebar,
            html.Main(id="page-content", className="content p-4"),
        ],
        className="app-shell",
    )
