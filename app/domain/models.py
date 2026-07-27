from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Client(BaseModel):
    id: int
    client_code: str = Field(pattern=r"^(?:client|test)_\d{4,}$", frozen=True)
    name: str
    client_type: str
    status: Literal["active", "inactive"]
    start_date: date
    end_date: date | None = None
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_client_lifecycle(self) -> "Client":
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class ClientExternalReference(BaseModel):
    id: int
    client_id: int
    source_system: str
    external_client_reference: str
    enabled: bool = True
    created_at: datetime
    updated_at: datetime


class Service(BaseModel):
    id: int
    code: str
    name: str
    description: str
    service_line: str


class PricingPlan(BaseModel):
    id: int
    name: str
    setup_fee: Decimal = Decimal("0")
    annual_fee: Decimal = Decimal("0")
    monthly_fixed_fee: Decimal = Decimal("0")
    included_documents: int = 0
    included_validations: int = 0
    included_graph_queries: int = 0
    included_blockchain_transactions: int = 0
    price_per_document: Decimal = Decimal("0")
    price_per_validation: Decimal = Decimal("0")
    price_per_graph_query: Decimal = Decimal("0")
    price_per_blockchain_transaction: Decimal = Decimal("0")
    price_per_property_mint: Decimal = Decimal("0")
    revenue_share_percentage: Decimal = Decimal("0")


class ClientSubscription(BaseModel):
    id: int
    client_id: int
    pricing_plan_id: int
    start_date: date
    end_date: date | None = None
    status: str = "active"
    notes: str | None = None


class UsageEvent(BaseModel):
    id: int
    client_id: int
    service_code: str
    event_type: str
    quantity: Decimal
    unit: str
    event_timestamp: datetime
    source_system: str
    external_reference_id: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class CostItem(BaseModel):
    id: int
    cost_key: str
    name: str
    provider: str | None = None
    category: str
    service_line: str | None = None
    cost_type: Literal["fixed", "variable"]
    charge_basis: Literal["flat", "per_user", "usage"]
    quantity: Decimal = Field(default=Decimal("1"), ge=0)
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0)
    entered_unit_cost: Decimal | None = Field(default=None, ge=0)
    unit: str
    billing_frequency: Literal["monthly", "annual", "usage", "once"]
    start_date: date | None = None
    end_date: date | None = None
    currency: str = "MXN"
    entered_currency: str | None = None
    record_type: Literal["actual", "budget", "estimate"] = "actual"
    enabled: bool = True
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "CostItem":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        valid_frequency = (
            self.billing_frequency == "usage"
            if self.cost_type == "variable"
            else self.billing_frequency in {"monthly", "annual", "once"}
        )
        if not valid_frequency:
            raise ValueError("cost_type and billing_frequency are inconsistent")
        return self

    @property
    def configured_amount(self) -> Decimal:
        """Amount for one configured recurrence or one-time occurrence."""

        return self.quantity * self.unit_cost

    @property
    def entered_configured_amount(self) -> Decimal:
        return self.quantity * (self.entered_unit_cost if self.entered_unit_cost is not None else self.unit_cost)

    @property
    def display_unit_cost(self) -> Decimal:
        return self.entered_unit_cost if self.entered_unit_cost is not None else self.unit_cost

    @property
    def display_currency(self) -> str:
        return self.entered_currency or self.currency


class RevenueEvent(BaseModel):
    id: int
    client_id: int
    service_code: str
    revenue_type: str
    amount: Decimal
    currency: str
    event_timestamp: datetime
    description: str | None = None


class ScenarioAssumption(BaseModel):
    id: int
    scenario_name: str
    assumption_key: str
    assumption_value: Decimal
    unit: str
    description: str | None = None


class ClientProfitability(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    client_id: int
    revenue: Decimal
    variable_cost: Decimal
    gross_margin: Decimal
    gross_margin_percentage: Decimal
