from django import template

register = template.Library()


@register.filter
def dot_thousands(value):
    try:
        return f"{int(value):,}".replace(",", ".")
    except (ValueError, TypeError):
        return value
