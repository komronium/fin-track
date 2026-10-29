from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def dot_thousands(value):
    """1500000 -> 1.500.000 ; 1234.5 -> 1.234,50 (European grouping, decimals kept when present)."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return value
    if not number.is_finite():
        return value
    if number == number.to_integral_value():
        return f"{int(number):,}".replace(",", ".")
    whole, _, frac = f"{number:,.2f}".partition(".")
    return f"{whole.replace(',', '.')},{frac}"
