from app.pages.pricing import layout


def test_pricing_plans_are_presented_before_the_simulator() -> None:
    page = layout()
    section_ids = [child.id for child in page.children if getattr(child, "id", None)]

    assert section_ids.index("pricing-plans-section") < section_ids.index("pricing-simulator-section")
