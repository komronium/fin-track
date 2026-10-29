from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def dot_thousands(value):
    try:
        return f"{int(value):,}".replace(",", ".")
    except (ValueError, TypeError):
        return value


@register.filter
def comma_thousands(value):
    """Same output as the dashboard script's Intl.NumberFormat('en-US', {maximumFractionDigits: 2}):
    1500000 -> 1,500,000 ; Decimal('12.50') -> 12.5"""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return value
    if not number.is_finite():
        return value
    number = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = f"{number:,.2f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


@register.filter
def comma_fixed2(value):
    """123868 -> 123,868.00 ; Decimal('0.5') -> 0.50 (grouped like the scripts' en-US formatting, always 2 decimals)."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return value
    if not number.is_finite():
        return value
    return f"{number.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"
