"""Order and payment transitions, shared by admin actions and their UI."""

from datetime import datetime, timezone

from app import db
from app.models import Order


def allowed_order_statuses(order):
    if order.status == "Pending Approval":
        return (
            ("Approved", "Declined")
            if order.payment_method == "COD/COP" or order.payment_status == "Paid"
            else ("Declined",)
        )
    if order.payment_method != "COD/COP" and order.payment_status != "Paid":
        return ()
    if order.status == "Approved":
        return ("In Progress",)
    if order.status == "In Progress":
        return ("Up for Delivery",) if order.order_type == "Delivery" else ("Completed",)
    if order.status == "Up for Delivery" and order.order_type == "Delivery":
        return ("Completed",)
    return ()


def _apply_changes(order, changes):
    # Compare the stored state so a stale admin page cannot overwrite a newer action.
    count = Order.query.filter_by(
        order_id=order.order_id,
        status=order.status,
        payment_status=order.payment_status,
        payment_method=order.payment_method,
        order_type=order.order_type,
    ).update(changes, synchronize_session=False)
    if count != 1:
        raise ValueError("This order changed. Refresh the page before trying again.")
    db.session.expire(order)


def transition_order(order, new_status, decline_reason=None):
    if new_status == order.status:
        return False
    if new_status not in allowed_order_statuses(order):
        raise ValueError("That status change is not allowed for this order.")
    changes = {"status": new_status}
    if new_status == "Declined":
        reason = (decline_reason or "").strip()
        if not reason:
            raise ValueError("A reason is required to decline an order.")
        changes["decline_reason"] = reason
    elif new_status == "Approved":
        changes["decline_reason"] = None
    elif new_status == "Completed":
        changes["completed_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
        # Selecting Completed confirms cash was collected; the UI states this explicitly.
        changes["payment_status"] = "Paid"
    _apply_changes(order, changes)
    return True


def verify_gcash_payment(order, approved):
    if (
        order.payment_method != "GCash"
        or order.status != "Pending Payment Verification"
        or order.payment_status != "Pending Verification"
    ):
        raise ValueError("Only GCash orders awaiting verification can be verified.")
    _apply_changes(
        order,
        {
            "status": "Approved" if approved else "Declined",
            "payment_status": "Paid" if approved else "Failed",
            "decline_reason": None
            if approved
            else "GCash payment verification failed. Please contact us to resolve or re-order.",
        },
    )
