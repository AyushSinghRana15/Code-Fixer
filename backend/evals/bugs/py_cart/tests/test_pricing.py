import pytest

from cart.pricing import add_tax, apply_discount, subtotal


def test_subtotal():
    assert subtotal([(10.0, 2), (5.5, 1)]) == 25.5


def test_no_discount_keeps_total():
    assert apply_discount(80.0, 0) == 80.0


def test_discount_rejects_bad_percent():
    with pytest.raises(ValueError):
        apply_discount(50.0, 120)


def test_add_tax():
    assert add_tax(100.0, 0.08) == 108.0
