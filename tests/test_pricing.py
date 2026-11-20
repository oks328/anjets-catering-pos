from decimal import Decimal
from types import SimpleNamespace

import pytest


def calculate_order_totals(*args, **kwargs):
    from app.routes import calculate_order_totals as calculate

    return calculate(*args, **kwargs)


def test_totals_use_exact_decimal_cents():
    result = calculate_order_totals([{"price": "0.10", "quantity": 3}], None)
    assert result["subtotal"] == Decimal("0.30")
    assert result["vat_amount"] == Decimal("0.04")
    assert result["final_total"] == Decimal("0.34")
    assert all(isinstance(amount, Decimal) for amount in result.values())


def test_discount_rounds_half_up_before_vat():
    result = calculate_order_totals(
        [{"price": "0.25", "quantity": 1}], None, voucher_code="SAVE", voucher_percent=2
    )
    assert result["discount_amount"] == Decimal("0.01")
    assert result["vat_amount"] == Decimal("0.03")
    assert result["final_total"] == Decimal("0.27")


def test_verified_discount_keeps_existing_allocation():
    customer = SimpleNamespace(is_verified_discount=True, discount_status="Approved")
    result = calculate_order_totals(
        [{"price": "100.01", "quantity": 2}],
        customer,
        delivery_fee="100.00",
        voucher_code="SAVE",
        voucher_percent=10,
    )
    assert result["vat_exempt_sales"] == Decimal("100.01")
    assert result["discount_amount"] == Decimal("20.00")
    assert result["vat_amount"] == Decimal("12.00")
    assert result["final_total"] == Decimal("292.02")


@pytest.mark.parametrize(
    "price,quantity",
    [
        ("NaN", 1),
        ("Infinity", 1),
        ("-1", 1),
        ("0", 1),
        ("0.001", 1),
        ("100", 0),
        ("100", -1),
        ("100", "1.5"),
    ],
)
def test_invalid_line_amount_is_rejected(price, quantity):
    with pytest.raises(ValueError):
        calculate_order_totals([{"price": price, "quantity": quantity}], None)


def test_order_total_cannot_exceed_database_precision():
    with pytest.raises(ValueError):
        calculate_order_totals([{"price": "99999999.99", "quantity": 2}], None)


@pytest.mark.parametrize("cents", [1, 5, 25, 99, 100, 10001, 999999])
@pytest.mark.parametrize("percentage", [0, 2, 10, 20])
def test_displayed_components_reconcile(cents, percentage):
    result = calculate_order_totals(
        [{"price": Decimal(cents) / 100, "quantity": 3}],
        None,
        delivery_fee="100",
        voucher_code="SAVE",
        voucher_percent=percentage,
    )
    assert result["final_total"] == (
        result["vatable_sales"]
        + result["vat_exempt_sales"]
        + result["vat_amount"]
        - result["discount_amount"]
        + Decimal("100.00")
    )
    assert all(amount.as_tuple().exponent == -2 for amount in result.values())


def test_generated_prices_match_independent_integer_cent_oracle():
    import random

    generator = random.Random(20261118)
    for _ in range(200):
        unit_cents = generator.randint(1, 1000000)
        quantity = generator.randint(1, 10)
        basis_points = generator.randint(0, 2000)
        delivery_cents = generator.choice([0, 10000])
        subtotal_cents = unit_cents * quantity
        discount_cents = (subtotal_cents * basis_points + 5000) // 10000
        vat_cents = ((subtotal_cents - discount_cents) * 12 + 50) // 100
        result = calculate_order_totals(
            [{"price": Decimal(unit_cents) / 100, "quantity": quantity}],
            None,
            delivery_fee=Decimal(delivery_cents) / 100,
            voucher_code="SAVE",
            voucher_percent=Decimal(basis_points) / 100,
        )
        assert (
            result["final_total"]
            == Decimal(subtotal_cents - discount_cents + vat_cents + delivery_cents) / 100
        )
