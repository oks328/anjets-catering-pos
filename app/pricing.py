"""Exact peso arithmetic. Round discounts and VAT to cents with ROUND_HALF_UP."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
MAX_MONEY = Decimal("99999999.99")
VAT_RATE = Decimal("0.12")


def positive_quantity(value):
    try:
        if isinstance(value, bool) or str(value) != str(int(value)):
            raise ValueError
        quantity = int(value)
        if quantity < 1 or quantity > 2147483647:
            raise ValueError
        return quantity
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Quantity must be a positive whole number.") from None


def money(value, positive=False):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < ZERO or amount > MAX_MONEY:
            raise ValueError
        rounded = amount.quantize(CENT, rounding=ROUND_HALF_UP)
        if rounded != amount or (positive and rounded <= ZERO):
            raise ValueError
        return rounded
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(
            "Amount must be a valid peso value with at most two decimal places, within 0.00–99,999,999.99."
            if not positive
            else "Price must be between 0.01 and 99,999,999.99, with at most two decimal places."
        ) from None


def calculate_order_totals(
    cart_items, customer, delivery_fee=0, voucher_code=None, voucher_percent=0
):
    subtotal = ZERO
    highest_unit_price = ZERO
    for item in cart_items:
        price = money(item["price"], positive=True)
        quantity = positive_quantity(item["quantity"])
        subtotal = money(subtotal + price * quantity)
        highest_unit_price = max(highest_unit_price, price)
    delivery_fee = money(delivery_fee)
    exempt = ZERO
    discount = ZERO
    vatable = subtotal
    if customer and customer.is_verified_discount and customer.discount_status == "Approved":
        # Preserve the existing policy: one highest-priced unit receives this allocation.
        exempt = highest_unit_price
        vatable = subtotal - exempt
        discount = (exempt * Decimal("0.20")).quantize(CENT, rounding=ROUND_HALF_UP)
        vat_base = vatable
    elif voucher_code:
        try:
            percent = Decimal(str(voucher_percent))
            if not percent.is_finite() or not ZERO <= percent <= Decimal("20"):
                raise ValueError
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("Voucher percentage must be between 0 and 20.") from None
        discount = (subtotal * percent / 100).quantize(CENT, rounding=ROUND_HALF_UP)
        vat_base = subtotal - discount
    else:
        vat_base = subtotal
    vat = (vat_base * VAT_RATE).quantize(CENT, rounding=ROUND_HALF_UP)
    final_total = money(subtotal - discount + vat + delivery_fee)
    return {
        "subtotal": subtotal,
        "vatable_sales": vatable,
        "vat_exempt_sales": exempt,
        "vat_amount": vat,
        "discount_amount": discount,
        "final_total": final_total,
    }
