from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


def to_jsonable(value: Any) -> Any:
    """Recursively convert Decimal/date/datetime/Pydantic values into JSON-safe types."""

    if isinstance(value, BaseModel):
        return to_jsonable(value.model_dump())
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    return value
