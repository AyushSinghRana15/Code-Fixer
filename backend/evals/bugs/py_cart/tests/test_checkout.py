from cart.checkout import checkout_total


def test_checkout_without_coupon():
    assert checkout_total([(50.0, 2)]) == 108.0
