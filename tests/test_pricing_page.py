from decimal import Decimal

from app.domain.models import PricingPlan
from app.pages.pricing import _included_document_price, layout


def _component_by_id(component, component_id: str):
    if getattr(component, "id", None) == component_id:
        return component
    children = getattr(component, "children", None)
    if children is None:
        return None
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        match = _component_by_id(child, component_id)
        if match is not None:
            return match
    return None


def test_pricing_plans_are_presented_before_the_simulator() -> None:
    page = layout()
    section_ids = [child.id for child in page.children if getattr(child, "id", None)]

    assert section_ids.index("pricing-plans-section") < section_ids.index("pricing-simulator-section")


def test_pricing_page_separates_platform_api_and_custom_terms() -> None:
    rendered = str(layout())

    assert "pricing-platform-table" in rendered
    assert "pricing-api-table" in rendered
    assert "Más popular" not in rendered
    assert "★" not in rendered
    assert "Price Per Document" in rendered
    assert "A la medida" in rendered
    assert "Precio por capacidad, no por usuario" in rendered
    assert "Graph queries" not in rendered


def test_implied_document_price_column_is_platform_only_and_follows_capacity() -> None:
    page = layout()
    platform_columns = [column["id"] for column in _component_by_id(page, "pricing-platform-table").columns]
    api_columns = [column["id"] for column in _component_by_id(page, "pricing-api-table").columns]

    assert platform_columns.index("price_per_document") == platform_columns.index("included_documents") + 1
    assert "price_per_document" not in api_columns


def test_included_document_price_uses_monthly_fee_and_included_capacity() -> None:
    core = PricingPlan(id=7, name="Core", monthly_fixed_fee=Decimal("6999"), included_documents=1000)
    enterprise = PricingPlan(id=9, name="Enterprise", monthly_fixed_fee=None, included_documents=None)

    assert _included_document_price(core) == Decimal("6.999")
    assert _included_document_price(enterprise) is None
