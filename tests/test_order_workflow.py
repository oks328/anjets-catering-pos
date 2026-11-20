import pytest

from app import db
from app.models import Order


def make_order(status="Pending Approval", method="COD/COP", payment="Pending", kind="Pickup"):
    order = Order(
        customer_id=1,
        total_amount=100,
        final_amount=112,
        status=status,
        payment_method=method,
        payment_status=payment,
        order_type=kind,
    )
    db.session.add(order)
    db.session.commit()
    return order


@pytest.fixture
def notices(monkeypatch):
    from app import routes

    sent = []
    monkeypatch.setattr(routes, "send_order_email", lambda *args: sent.append(args))
    return sent


@pytest.mark.parametrize(
    "old,new,kind",
    [
        ("Pending Approval", "Completed", "Pickup"),
        ("Approved", "Completed", "Pickup"),
        ("In Progress", "Approved", "Pickup"),
        ("Completed", "In Progress", "Pickup"),
        ("Declined", "Approved", "Pickup"),
        ("Pending Approval", "unexpected", "Pickup"),
        ("In Progress", "Up for Delivery", "Pickup"),
        ("In Progress", "Completed", "Delivery"),
    ],
)
def test_invalid_transition_keeps_order(admin, csrf, notices, old, new, kind):
    order = make_order(old, kind=kind)
    admin.post(
        f"/admin/orders/update_status/{order.order_id}", data={"csrf_token": csrf, "status": new}
    )
    db.session.refresh(order)
    assert order.status == old
    assert not notices


@pytest.mark.parametrize("reason", ["", "   "])
def test_decline_requires_reason(admin, csrf, notices, reason):
    order = make_order()
    admin.post(
        f"/admin/orders/update_status/{order.order_id}",
        data={"csrf_token": csrf, "status": "Declined", "decline_reason": reason},
    )
    db.session.refresh(order)
    assert order.status == "Pending Approval"
    assert not notices


@pytest.mark.parametrize(
    "old,new,kind",
    [
        ("Pending Approval", "Approved", "Pickup"),
        ("Approved", "In Progress", "Pickup"),
        ("In Progress", "Completed", "Pickup"),
        ("In Progress", "Up for Delivery", "Delivery"),
        ("Up for Delivery", "Completed", "Delivery"),
    ],
)
def test_valid_transition_advances_order(admin, csrf, notices, old, new, kind):
    order = make_order(old, kind=kind)
    admin.post(
        f"/admin/orders/update_status/{order.order_id}", data={"csrf_token": csrf, "status": new}
    )
    db.session.refresh(order)
    assert order.status == new
    assert len(notices) == 1
    if new == "Completed":
        assert order.payment_status == "Paid"
        assert order.completed_at is not None


def test_gcash_cannot_bypass_verification(admin, csrf, notices):
    order = make_order("Pending Payment Verification", "GCash", "Pending Verification")
    admin.post(
        f"/admin/orders/update_status/{order.order_id}",
        data={"csrf_token": csrf, "status": "Approved"},
    )
    db.session.refresh(order)
    assert order.status == "Pending Payment Verification"
    assert not notices


@pytest.mark.parametrize("action", ["approve", "deny"])
@pytest.mark.parametrize(
    "status,method,payment",
    [
        ("Completed", "GCash", "Paid"),
        ("Pending Approval", "COD/COP", "Pending"),
        ("Declined", "GCash", "Failed"),
    ],
)
def test_verification_rejects_wrong_state(admin, csrf, notices, action, status, method, payment):
    order = make_order(status, method, payment)
    admin.post(f"/admin/{action}_payment/{order.order_id}", data={"csrf_token": csrf})
    db.session.refresh(order)
    assert (order.status, order.payment_status) == (status, payment)
    assert not notices


@pytest.mark.parametrize(
    "action,status,payment",
    [
        ("approve", "Approved", "Paid"),
        ("deny", "Declined", "Failed"),
    ],
)
def test_verification_updates_once(admin, csrf, notices, action, status, payment):
    order = make_order("Pending Payment Verification", "GCash", "Pending Verification")
    for _ in range(2):
        admin.post(f"/admin/{action}_payment/{order.order_id}", data={"csrf_token": csrf})
    db.session.refresh(order)
    assert (order.status, order.payment_status) == (status, payment)
    assert len(notices) == 1


def test_notification_failure_does_not_report_transaction_failure(admin, csrf, monkeypatch):
    from app import routes

    order = make_order()

    def fail_email(*args):
        raise RuntimeError("private-mail-server-detail")

    monkeypatch.setattr(routes, "send_order_email", fail_email)
    admin.post(
        f"/admin/orders/update_status/{order.order_id}",
        data={"csrf_token": csrf, "status": "Approved"},
    )
    db.session.refresh(order)
    assert order.status == "Approved"
    with admin.session_transaction() as session:
        messages = str(session.get("_flashes"))
        assert "private-mail-server-detail" not in messages
        assert "notification" in messages.lower()


def test_order_page_offers_only_next_step(admin, app, notices):
    make_order("Completed", payment="Paid")
    html = admin.get("/admin/orders").get_data(as_text=True)
    assert '<option value="In Progress">' not in html
    assert '<option value="Completed">' not in html


@pytest.mark.parametrize("status", ["Pending Approval", "Pending Payment Verification", "Declined"])
def test_unapproved_order_has_no_receipt(checkout, status):
    order = make_order(status)
    response = checkout.get(f"/my-account/order/{order.order_id}/receipt")
    assert response.status_code == 302
    assert response.location.endswith("/my-account/orders")


def test_unpaid_order_summary_does_not_claim_payment(checkout):
    order = make_order("Approved")
    html = checkout.get(f"/my-account/order/{order.order_id}/receipt").get_data(as_text=True)
    assert "Total Paid:" not in html
    assert "Total Due:" in html
