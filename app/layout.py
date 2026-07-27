import dash_bootstrap_components as dbc
from dash import dcc, html

from app.theme import theme_store, theme_toggle

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
                            html.Div("Valteh", className="brand-name"),
                            html.Div("Economics Dashboard", className="brand-product"),
                        ]
                    ),
                ],
                className="brand-header",
            ),
            theme_toggle(),
            dbc.Nav(
                [dbc.NavLink(label, href=href, active="exact") for label, href in NAV_ITEMS],
                vertical=True,
                pills=True,
            ),
        ],
        className="sidebar",
    )
    return html.Div(
        [
            dcc.Location(id="url"),
            theme_store(),
            sidebar,
            html.Main(id="page-content", className="content"),
        ],
        className="app-shell",
    )
