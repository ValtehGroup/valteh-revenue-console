from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from app.domain.cost_engine import CostAmount
from app.domain.fx_rates import FxRateUnavailableError, ResolvedFxRate
from app.domain.revenue_engine import RevenueAmount

DISPLAY_CURRENCIES = ("MXN", "USD")
DEFAULT_DISPLAY_CURRENCY = "MXN"


def normalize_display_currency(value: str | None) -> str:
    currency = (value or DEFAULT_DISPLAY_CURRENCY).strip().upper()
    if currency not in DISPLAY_CURRENCIES:
        raise ValueError(f"Unsupported display currency '{currency}'. Use MXN or USD.")
    return currency


def translate_mxn(
    amount_mxn: Decimal,
    display_currency: str,
    rate: ResolvedFxRate | Decimal | None = None,
) -> Decimal:
    currency = normalize_display_currency(display_currency)
    if currency == "MXN":
        return amount_mxn
    exchange_rate = rate.rate if isinstance(rate, ResolvedFxRate) else rate
    if exchange_rate is None or not exchange_rate.is_finite() or exchange_rate <= 0:
        raise FxRateUnavailableError("A positive persisted USD/MXN FIX rate is required for USD presentation.")
    return amount_mxn / exchange_rate


def translate_revenue_amount(
    amount: RevenueAmount,
    display_currency: str,
    rates_by_date: Mapping[date, ResolvedFxRate],
) -> Decimal:
    currency = normalize_display_currency(display_currency)
    if currency == "MXN":
        return amount.amount_mxn
    return translate_mxn(amount.amount_mxn, currency, _required_rate(rates_by_date, amount.recognition_date))


def translate_cost_amount(
    amount: CostAmount,
    display_currency: str,
    rates_by_date: Mapping[date, ResolvedFxRate],
) -> Decimal:
    currency = normalize_display_currency(display_currency)
    if currency == "MXN":
        return amount.amount
    if amount.valuation_date is None:
        raise FxRateUnavailableError(f"Cost '{amount.cost_key}' has no recognition date for USD presentation.")
    if amount.source_currency == "USD":
        if amount.fx_rate is None or not amount.fx_rate.is_finite() or amount.fx_rate <= 0:
            raise FxRateUnavailableError(
                f"USD cost '{amount.cost_key}' has no valid applied FIX for {amount.valuation_date.isoformat()}."
            )
        return amount.amount / amount.fx_rate
    return translate_mxn(amount.amount, currency, _required_rate(rates_by_date, amount.valuation_date))


def format_currency(value: Decimal | float | int, display_currency: str, *, decimals: int = 0) -> str:
    currency = normalize_display_currency(display_currency)
    return f"${float(value):,.{decimals}f} {currency}"


def format_compact_currency(value: Decimal | float | int, display_currency: str) -> str:
    currency = normalize_display_currency(display_currency)
    number = Decimal(str(value))
    if abs(number) >= Decimal("1000"):
        return f"${number / Decimal('1000'):,.1f}k {currency}"
    return f"${number:,.1f} {currency}"


def usd_view_note(display_currency: str, *, scenario: bool = False):
    if normalize_display_currency(display_currency) != "USD":
        return None
    from dash import html

    label = "USD view · scenario FX assumptions" if scenario else "USD view · historical FIX by recognition date"
    tooltip = (
        "Projected amounts use the USD/MXN assumption applicable to each scenario row."
        if scenario
        else (
            "Revenue, costs and margins are translated using the persisted Banxico FIX applicable to each "
            "recognized transaction."
        )
    )
    return html.Div(
        label,
        className="display-currency-note small text-muted mb-3",
        title=tooltip,
    )


def _required_rate(
    rates_by_date: Mapping[date, ResolvedFxRate],
    recognition_date: date,
) -> ResolvedFxRate:
    try:
        return rates_by_date[recognition_date]
    except KeyError as exc:
        raise FxRateUnavailableError(
            f"USD/MXN FIX is unavailable for recognition date {recognition_date.isoformat()}."
        ) from exc
