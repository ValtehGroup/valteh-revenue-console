from dash import dcc

from app.layout import GUIDE_ITEM, NAV_ITEMS, app_layout
from app.pages import user_guide
from app.routes import page_layout


def test_user_guide_is_linked_and_renders_repository_markdown() -> None:
    assert GUIDE_ITEM == ("User Guide", "/guide")
    assert GUIDE_ITEM not in NAV_ITEMS

    sidebar_footer = next(
        component
        for component in _walk(app_layout())
        if getattr(component, "className", None) == "sidebar-footer"
    )
    assert sidebar_footer.children[0].href == "/guide"

    page = page_layout("/guide")
    markdown = page.children

    assert isinstance(markdown, dcc.Markdown)
    assert markdown.link_target == "_blank"
    assert "## Costs" in markdown.children
    assert "## Clients" in markdown.children
    assert markdown.children == user_guide.GUIDE_PATH.read_text(encoding="utf-8")


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        yield from _walk(child)
