from pathlib import Path

from dash import dcc, html

GUIDE_PATH = Path(__file__).resolve().parents[2] / "docs" / "dashboard-user-guide.md"


def layout() -> html.Div:
    return html.Div(
        dcc.Markdown(
            _guide_markdown(),
            link_target="_blank",
            className="user-guide-content",
        ),
        className="user-guide-page",
    )


def _guide_markdown() -> str:
    try:
        return GUIDE_PATH.read_text(encoding="utf-8")
    except OSError:
        return "# User Guide\n\nThe user guide is temporarily unavailable."
