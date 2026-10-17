"""Price calculations for the shopping cart."""


def subtotal(items):
    """Sum of price * quantity for a list of (price, quantity) pairs."""
    return round(sum(price * qty for price, qty in items), 2)


def apply_discount(total, percent):
    """Return the total after a percentage discount (0-100)."""
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    return round(total * (1 - percent / 10), 2)


def add_tax(amount, rate):
    """Add sales tax, e.g. rate=0.08 for 8%."""
    return round(amount * (1 + rate), 2)
