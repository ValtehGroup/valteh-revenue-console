import os
from pathlib import Path

import dash
import dash_bootstrap_components as dbc

from app.api import api_bp
from app.config import get_settings
from app.data.seed_data import seed_database
from app.layout import app_layout
from app.routes import register_routes
from app.theme import THEME_INDEX_STRING, register_theme_callbacks


def create_app() -> dash.Dash:
    seed_database()
    settings = get_settings()
    assets_folder = Path(__file__).resolve().parent / "assets"
    app = dash.Dash(
        __name__,
        external_stylesheets=[dbc.themes.BOOTSTRAP],
        suppress_callback_exceptions=True,
        assets_folder=str(assets_folder),
        title=settings.app_name,
    )
    app.index_string = THEME_INDEX_STRING
    app.layout = app_layout()
    app.server.register_blueprint(api_bp)
    register_routes(app)
    register_theme_callbacks(app)
    return app


app = create_app()
server = app.server


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8050"))
    app.run(debug=get_settings().debug, host="127.0.0.1", port=port)
