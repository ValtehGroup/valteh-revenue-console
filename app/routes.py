from dash import Input, Output

from app.pages import client_detail, clients, costs, executive_dashboard, pricing, scenarios, usage


def register_routes(app) -> None:
    executive_dashboard.register_callbacks(app)
    client_detail.register_callbacks(app)
    clients.register_callbacks(app)
    costs.register_callbacks(app)
    pricing.register_callbacks(app)
    scenarios.register_callbacks(app)

    @app.callback(Output("page-content", "children"), Input("url", "pathname"))
    def render_page(pathname: str):
        if pathname == "/clients":
            return clients.layout()
        if pathname == "/client-detail":
            return clients.layout()
        if pathname == "/costs":
            return costs.layout()
        if pathname == "/pricing":
            return pricing.layout()
        if pathname == "/usage":
            return usage.layout()
        if pathname == "/scenarios":
            return scenarios.layout()
        return executive_dashboard.layout()
