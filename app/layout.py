import dash_bootstrap_components as dbc
from dash import dcc, html

from app.theme import theme_store, theme_toggle

NAV_ITEMS = [
    ("Executive Summary", "/"),
    ("Clients", "/clients"),
    ("Costs", "/costs"),
    ("Pricing", "/pricing"),
    ("Usage", "/usage"),
    ("Scenarios", "/scenarios"),
]
GUIDE_ITEM = ("User Guide", "/guide")


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
            dbc.Nav(
                [dbc.NavLink(label, href=href, active="exact") for label, href in NAV_ITEMS],
                vertical=True,
                pills=True,
            ),
            html.Div(
                [
                    dbc.NavLink(GUIDE_ITEM[0], href=GUIDE_ITEM[1], active="exact"),
                    theme_toggle(),
                ],
                className="sidebar-footer",
            ),
        ],
        className="sidebar",
    )
    return html.Div(
        [
            dcc.Location(id="url"),
            theme_store(),
            dcc.Store(id="anthropic-live-report-cache", storage_type="session"),
            sidebar,
            html.Main(id="page-content", className="content"),
        ],
        className="app-shell",
    )
