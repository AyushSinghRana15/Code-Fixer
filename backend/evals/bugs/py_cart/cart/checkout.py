from cart.pricing import add_tax, apply_discount, subtotal


def checkout_total(items, coupon_percent=0, tax_rate=0.08):
    """Final amount to charge: subtotal, minus any coupon, plus tax."""
    total = subtotal(items)
    if coupon_percent:
        total = apply_discount(total, coupon_percent)
    return add_tax(total, tax_rate)
