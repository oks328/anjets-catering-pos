"""Server-side validation shared by checkout entry points."""

import json
from datetime import date, datetime, timedelta
from hashlib import sha256

from app import db
from app.models import ProductVariant, Voucher
from app.pricing import calculate_order_totals, money, positive_quantity

CHECKOUT_KEYS = (
    "cart",
    "voucher_code",
    "discount_percentage",
    "delivery_fee",
    "order_type",
    "delivery_address",
    "buffet_package",
    "buffet_recommendations",
    "buffet_sequence",
    "buffet_guest_count",
    "event_date_str",
    "event_time_str",
    "payment_method",
    "gcash_image_file",
    "gcash_reference_no",
    "final_total",
    "card_last_four",
    "card_type",
    "card_holder_name",
    "checkout_token",
    "checkout_quote",
    "gcash_quote",
)


def clear_checkout_session(session):
    for key in CHECKOUT_KEYS:
        session.pop(key, None)


def validate_cart(cart):
    if not isinstance(cart, dict) or not cart:
        raise ValueError("Your cart is empty.")
    items = []
    for key, item in cart.items():
        if not isinstance(item, dict):
            raise ValueError("Your cart is invalid. Please rebuild it.")
        quantity = positive_quantity(item.get("quantity"))
        variant_id = str(item.get("variant_id", key)).removeprefix("buffet_")
        try:
            variant = db.session.get(ProductVariant, int(variant_id))
        except (TypeError, ValueError, OverflowError):
            variant = None
        if not variant or not variant.product.is_active or not variant.product.category.is_active:
            raise ValueError("An item is no longer available. Please update your cart.")
        price = money(variant.price, positive=True)
        items.append(
            {
                "variant_id": variant.variant_id,
                "product_id": variant.product_id,
                "price": price,
                "quantity": quantity,
                "product_name": variant.product.name,
                "variant_name": variant.size_name,
                "image": variant.product.image_file,
                "cart_key": key,
                "is_buffet_item": bool(item.get("is_buffet_item")),
            }
        )
    return items


def validate_event_details(details, items):
    try:
        event_date = datetime.strptime(details.get("event_date_str") or "", "%Y-%m-%d").date()
        event_time = datetime.strptime(details.get("event_time_str") or "", "%H:%M").time()
    except (ValueError, TypeError):
        raise ValueError("Please select a valid event date and time.") from None
    lead_days = 7 if any(item.get("is_buffet_item") for item in items) else 3
    if event_date < date.today() + timedelta(days=lead_days):
        raise ValueError(f"This order requires at least {lead_days} days lead time.")
    if details.get("payment_method") not in ("COD/COP", "GCash"):
        raise ValueError("Please select GCash or cash on delivery/pickup.")
    if details.get("order_type") not in ("Pickup", "Delivery"):
        raise ValueError("Please select pickup or delivery.")
    if details["order_type"] == "Delivery" and not (details.get("delivery_address") or "").strip():
        raise ValueError("Please provide a delivery address.")
    return event_date, event_time


def quote_signature(items, totals, details):
    payload = {
        "items": [
            {
                key: str(item[key])
                for key in (
                    "variant_id",
                    "product_id",
                    "quantity",
                    "price",
                    "product_name",
                    "variant_name",
                    "is_buffet_item",
                )
            }
            for item in items
        ],
        "totals": {key: str(value) for key, value in totals.items()},
        "details": {
            key: details.get(key)
            for key in (
                "event_date_str",
                "event_time_str",
                "order_type",
                "delivery_address",
                "payment_method",
                "voucher_code",
            )
        },
    }
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def current_quote(details, customer):
    items = validate_cart(details.get("cart"))
    voucher_code = details.get("voucher_code")
    percent = 0
    if customer.is_verified_discount and customer.discount_status == "Approved":
        voucher_code = None
    if voucher_code:
        voucher = Voucher.query.filter_by(code=voucher_code, is_active=True).first()
        if not voucher or (
            voucher.max_uses is not None and voucher.current_uses >= voucher.max_uses
        ):
            raise ValueError(
                "This voucher is no longer available. Please remove it from your cart."
            )
        percent = voucher.discount_percentage
    fee = 100 if details.get("order_type") == "Delivery" else 0
    totals = calculate_order_totals(items, customer, fee, voucher_code, percent)
    return items, totals, quote_signature(items, totals, details)


def invalidate_quote(details):
    for key in (
        "checkout_quote",
        "gcash_quote",
        "gcash_image_file",
        "gcash_reference_no",
        "final_total",
    ):
        details.pop(key, None)
