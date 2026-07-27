from dash import ClientsideFunction, Input, Output, State, dcc, html

VALID_THEMES = {"light", "dark"}

THEME_INDEX_STRING = """<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <script>
            (function () {
                var theme = null;
                try {
                    theme = window.localStorage.getItem("valteh-theme");
                } catch (_error) {}
                if (theme !== "light" && theme !== "dark") {
                    theme = window.matchMedia &&
                        window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
                }
                document.documentElement.dataset.theme = theme;
                document.cookie = "valteh-theme=" + theme + "; path=/; max-age=31536000; samesite=lax";
            })();
        </script>
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>"""


def normalize_theme(value: str | None) -> str:
    return value if value in VALID_THEMES else "light"


def theme_store() -> dcc.Store:
    return dcc.Store(id="theme-store", storage_type="local")


def theme_toggle() -> html.Button:
    return html.Button(
        html.Span(
            [
                html.Span(
                    "☀",
                    id="theme-toggle-icon",
                    className="theme-toggle-icon",
                    **{"aria-hidden": "true"},
                ),
                html.Span("Light", id="theme-toggle-label", className="theme-toggle-label"),
            ],
            className="theme-toggle-state",
        ),
        id="theme-toggle",
        type="button",
        className="theme-toggle",
        n_clicks=0,
        title="Switch to dark theme",
        **{
            "aria-label": "Switch to dark theme",
            "aria-pressed": "false",
        },
    )


def register_theme_callbacks(app) -> None:
    app.clientside_callback(
        ClientsideFunction(namespace="valtehTheme", function_name="toggleTheme"),
        Output("theme-store", "data"),
        Input("theme-toggle", "n_clicks"),
        State("theme-store", "data"),
    )
    app.clientside_callback(
        ClientsideFunction(namespace="valtehTheme", function_name="syncTheme"),
        Output("theme-toggle-icon", "children"),
        Output("theme-toggle-label", "children"),
        Output("theme-toggle", "aria-label"),
        Output("theme-toggle", "title"),
        Output("theme-toggle", "aria-pressed"),
        Input("theme-store", "data"),
        Input("url", "pathname"),
    )
