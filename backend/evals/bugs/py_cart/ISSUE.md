Coupons give wrong totals at checkout

A customer with a 15% coupon on a $200 cart was charged a negative amount.
`apply_discount(200, 15)` returns -100.0 but it should return 170.0.
Small coupons look wrong too: a 5% coupon on $100 gives 50.0 instead of 95.0.
