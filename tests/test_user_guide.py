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
    guide_nav, guide_content = page.children
    markdown_components = [
        component for component in _walk(guide_content) if isinstance(component, dcc.Markdown)
    ]
    rendered_markdown = "\n\n".join(component.children for component in markdown_components)
    nav_links = [
        component
        for component in _walk(guide_nav)
        if getattr(component, "href", "").startswith("#")
    ]

    assert guide_nav.className == "user-guide-nav"
    assert guide_content.className == "user-guide-content"
    assert {link.href for link in nav_links} >= {
        "#general-interaction",
        "#executive-dashboard",
        "#clients",
        "#costs",
        "#pricing",
        "#usage",
        "#scenarios",
        "#quick-decision-guide",
    }
    assert all(component.link_target == "_blank" for component in markdown_components)
    assert "## Costs" in rendered_markdown
    assert "## Clients" in rendered_markdown
    assert "## Pricing" in rendered_markdown
    assert "## Usage" in rendered_markdown
    assert "## Scenarios" in rendered_markdown
    assert "## In this guide" not in rendered_markdown
    assert "## In this guide" in user_guide.GUIDE_PATH.read_text(encoding="utf-8")


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        yield from _walk(child)
