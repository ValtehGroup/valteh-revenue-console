import re
from pathlib import Path

from dash.development.base_component import Component

from app.components.chart_theme import (
    DEFAULT_PLOTLY_COLORWAY,
    PLOTLY_THEME,
    apply_chart_theme,
    plotly_template,
)
from app.components.charts import bar_chart, pie_chart
from app.layout import app_layout
from app.main import create_app
from app.theme import THEME_INDEX_STRING, normalize_theme

ASSETS_DIR = Path(__file__).resolve().parents[1] / "app" / "assets"


def _theme_tokens(theme: str) -> dict[str, str]:
    css = (ASSETS_DIR / "00_tokens.css").read_text(encoding="utf-8")
    pattern = (
        r':root,\s*\[data-theme="light"\]\s*\{(?P<body>.*?)\}'
        if theme == "light"
        else r'\[data-theme="dark"\]\s*\{(?P<body>.*?)\}'
    )
    match = re.search(pattern, css, flags=re.DOTALL)
    assert match is not None
    return dict(re.findall(r"--([\w-]+):\s*([^;]+);", match.group("body")))


def _relative_luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def _walk(component):
    yield component
    if not isinstance(component, Component):
        return
    children = getattr(component, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        yield from _walk(child)


def test_both_theme_scopes_define_essential_tokens() -> None:
    theme_specific = {
        "color-bg",
        "color-surface",
        "color-surface-elevated",
        "color-text",
        "color-text-muted",
        "color-primary",
        "color-primary-hover",
        "color-primary-contrast",
        "color-secondary",
        "color-accent",
        "color-border",
        "color-success",
        "color-warning",
        "color-danger",
        "shadow-sm",
        "shadow-md",
    }
    shared = {
        "radius-sm",
        "radius-md",
        "space-1",
        "space-2",
        "space-3",
        "space-4",
    }

    for theme in ("light", "dark"):
        tokens = _theme_tokens(theme)
        assert theme_specific <= tokens.keys()
    light_tokens = _theme_tokens("light")
    assert shared <= light_tokens.keys()
    assert light_tokens["font-family"].startswith('"Segoe UI"')


def test_core_theme_combinations_meet_wcag_contrast() -> None:
    for theme in ("light", "dark"):
        tokens = _theme_tokens(theme)
        assert _contrast_ratio(tokens["color-text"], tokens["color-bg"]) >= 4.5
        assert _contrast_ratio(tokens["color-text-muted"], tokens["color-surface"]) >= 4.5
        assert _contrast_ratio(tokens["color-primary-contrast"], tokens["color-primary"]) >= 4.5
        assert _contrast_ratio(tokens["color-focus"], tokens["color-bg"]) >= 3
        assert _contrast_ratio(tokens["color-border-strong"], tokens["color-surface"]) >= 3


def test_dark_theme_uses_saremi_brand_palette() -> None:
    tokens = _theme_tokens("dark")

    assert tokens["color-bg"] == "#09090b"
    assert tokens["color-surface"] == "#131316"
    assert tokens["color-primary"] == "#00b4b4"
    assert tokens["color-primary-hover"] == "#4dd8d8"
    assert tokens["color-depth"] == "#0b3a82"
    assert tokens["color-danger"] == "#ef4444"


def test_dash_four_dropdowns_use_semantic_theme_tokens() -> None:
    css = (ASSETS_DIR / "20_components.css").read_text(encoding="utf-8")

    assert ".dash-dropdown-content" in css
    assert "--Dash-Fill-Inverse-Strong: var(--color-surface)" in css
    assert "--Dash-Text-Strong: var(--color-text)" in css
    assert ".dash-dropdown-value" in css
    assert ".dash-dropdown-option[data-highlighted]" in css


def test_plotly_templates_are_transparent_and_theme_specific() -> None:
    for theme in ("light", "dark"):
        template = plotly_template(theme)
        layout = template.layout

        assert layout.paper_bgcolor == "rgba(0,0,0,0)"
        assert layout.plot_bgcolor == "rgba(0,0,0,0)"
        assert layout.font.color == PLOTLY_THEME[theme]["text"]
        assert "Segoe UI" in layout.font.family
        assert list(layout.colorway) == PLOTLY_THEME[theme]["colorway"]
        assert layout.xaxis.gridcolor == PLOTLY_THEME[theme]["grid"]


def test_apply_chart_theme_normalizes_unknown_theme() -> None:
    import plotly.graph_objects as go

    figure = apply_chart_theme(go.Figure(), "unsupported")
    template_layout = figure.layout.template.layout

    assert template_layout.font.color == PLOTLY_THEME["light"]["text"]
    assert list(template_layout.colorway) == PLOTLY_THEME["light"]["colorway"]


def test_charts_can_keep_plotly_default_colors_with_theme_aware_layout() -> None:
    bar = bar_chart({"SAREMI": 1}, "Bar", default_plotly_colors=True)
    pie = pie_chart({"SAREMI": 1, "Graphos": 2}, "Pie", default_plotly_colors=True)

    assert bar.data[0].marker.color == DEFAULT_PLOTLY_COLORWAY[0]
    assert list(bar.layout.template.layout.colorway) == DEFAULT_PLOTLY_COLORWAY
    assert list(pie.layout.template.layout.colorway) == DEFAULT_PLOTLY_COLORWAY
    assert pie.layout.template.layout.paper_bgcolor == "rgba(0,0,0,0)"


def test_plotly_template_uses_theme_cookie_during_callbacks() -> None:
    from flask import Flask

    flask_app = Flask(__name__)
    with flask_app.test_request_context(
        "/",
        environ_overrides={"HTTP_COOKIE": "valteh-theme=dark"},
    ):
        template = plotly_template()

    assert template.layout.font.color == PLOTLY_THEME["dark"]["text"]
    assert list(template.layout.colorway) == PLOTLY_THEME["dark"]["colorway"]


def test_theme_toggle_and_local_store_are_in_the_app_shell() -> None:
    components = {getattr(component, "id", None): component for component in _walk(app_layout())}

    assert components["theme-store"].storage_type == "local"
    assert components["theme-toggle"].type == "button"
    toggle_props = components["theme-toggle"].to_plotly_json()["props"]
    assert toggle_props["aria-label"]
    assert toggle_props["aria-pressed"] == "false"


def test_theme_initialization_is_early_valid_and_persistent() -> None:
    script = (ASSETS_DIR / "theme-init.js").read_text(encoding="utf-8")

    assert normalize_theme("light") == "light"
    assert normalize_theme("dark") == "dark"
    assert normalize_theme("unsupported") == "light"
    assert "localStorage" in THEME_INDEX_STRING
    assert "prefers-color-scheme" in THEME_INDEX_STRING
    assert "document.documentElement.dataset.theme" in THEME_INDEX_STRING
    assert "localStorage.setItem" in script
    assert "document.cookie" in script
    assert "MutationObserver" not in script
    assert "Plotly.relayout" not in script


def test_theme_callbacks_register_without_output_conflicts() -> None:
    app = create_app()

    assert "theme-store.data" in app.callback_map
    assert sum(key == "theme-store.data" for key in app.callback_map) == 1
    assert any("theme-toggle.aria-label" in key for key in app.callback_map)
    assert any("theme-toggle.aria-pressed" in key for key in app.callback_map)
