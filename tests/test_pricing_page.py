from app.pages.pricing import layout


def test_pricing_plans_are_presented_before_the_simulator() -> None:
    page = layout()
    section_ids = [child.id for child in page.children if getattr(child, "id", None)]

    assert section_ids.index("pricing-plans-section") < section_ids.index("pricing-simulator-section")


def test_pricing_page_separates_platform_api_and_custom_terms() -> None:
    rendered = str(layout())

    assert "pricing-platform-table" in rendered
    assert "pricing-api-table" in rendered
    assert "Más popular" in rendered
    assert "A la medida" in rendered
    assert "Precio por capacidad, no por usuario" in rendered
    assert "Graph queries" not in rendered
