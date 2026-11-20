"""Consistent sales totals and business-day boundaries for HTML and CSV reports."""

from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy import func

from app import db
from app.models import Order, OrderItem, Product, ProductVariant


def business_timezone():
    return ZoneInfo(current_app.config.get("BUSINESS_TIMEZONE", "Asia/Manila"))


def utc_boundary(day):
    return (
        datetime.combine(day, time.min, business_timezone())
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


def sales_filters(start, end):
    return (
        Order.status == "Completed",
        Order.payment_status == "Paid",
        Order.completed_at >= utc_boundary(start),
        Order.completed_at < utc_boundary(end + timedelta(days=1)),
    )


def sales_report(start_text=None, end_text=None):
    today = datetime.now(business_timezone()).date()
    try:
        start = (
            datetime.strptime(start_text, "%Y-%m-%d").date()
            if start_text
            else today - timedelta(days=29)
        )
        end = datetime.strptime(end_text, "%Y-%m-%d").date() if end_text else today
    except (TypeError, ValueError):
        raise ValueError("Please enter valid start and end dates.") from None
    if start > end:
        raise ValueError("The start date must be on or before the end date.")
    filters = sales_filters(start, end)
    totals = defaultdict(lambda: Decimal("0.00"))
    for completed_at, amount in db.session.query(Order.completed_at, Order.final_amount).filter(
        *filters
    ):
        local_day = completed_at.replace(tzinfo=timezone.utc).astimezone(business_timezone()).date()
        totals[local_day] += amount
    sales_by_day = [
        SimpleNamespace(date=day, total_sales=totals[day]) for day in sorted(totals, reverse=True)
    ]
    product_label = func.coalesce(
        OrderItem.product_name_snapshot, Product.name, "Unavailable product"
    )
    variant_label = func.coalesce(
        OrderItem.variant_name_snapshot, ProductVariant.size_name, "Unavailable variant"
    )
    top_items = (
        db.session.query(
            product_label.label("name"),
            variant_label.label("size_name"),
            func.sum(OrderItem.quantity).label("total_sold"),
        )
        .select_from(OrderItem)
        .outerjoin(Product)
        .outerjoin(
            ProductVariant,
            ProductVariant.variant_id == OrderItem.variant_id,
        )
        .join(Order, Order.order_id == OrderItem.order_id)
        .filter(*filters)
        .group_by(
            OrderItem.product_id,
            OrderItem.variant_id,
            product_label,
            variant_label,
        )
        .order_by(func.sum(OrderItem.quantity).desc(), product_label)
        .all()
    )
    return {
        "sales_by_day": sales_by_day,
        "top_selling_items": top_items,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "date_range_str": f"{start.isoformat()} to {end.isoformat()}",
    }
