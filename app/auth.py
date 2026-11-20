"""Session proofs tied to current credentials for customers and administrators."""

import hashlib
import hmac
from functools import wraps

from flask import current_app, flash, redirect, session, url_for
from flask_login import logout_user

from app import db
from app.checkout import clear_checkout_session
from app.models import Customer, User


def credential_signature(account):
    value = f"{account.__tablename__}:{account.get_id()}:{account.password_hash or ''}"
    return hmac.new(current_app.secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()


def sign_in_customer(customer):
    clear_checkout_session(session)
    session["customer_id"] = customer.customer_id
    session["customer_name"] = customer.name
    session["customer_auth_version"] = credential_signature(customer)


def validate_customer_session():
    customer_id = session.get("customer_id")
    if customer_id is None:
        return
    customer = db.session.get(Customer, customer_id)
    proof = session.get("customer_auth_version", "")
    if (
        not customer
        or not isinstance(proof, str)
        or not hmac.compare_digest(proof, credential_signature(customer))
    ):
        clear_checkout_session(session)
        for key in ("customer_id", "customer_name", "customer_auth_version"):
            session.pop(key, None)


def validate_admin_session():
    user_id = session.get("_user_id")
    if user_id is None:
        return
    try:
        user = db.session.get(User, int(user_id))
    except (ValueError, TypeError):
        user = None
    proof = session.get("admin_auth_version", "")
    if (
        not user
        or not isinstance(proof, str)
        or not hmac.compare_digest(proof, credential_signature(user))
    ):
        logout_user()
        session.pop("admin_auth_version", None)


def customer_login_required(view):
    """Require the customer session already validated by request middleware."""

    @wraps(view)
    def decorated(*args, **kwargs):
        if "customer_id" not in session:
            flash("You must be logged in to view that page.", "danger")
            return redirect(url_for("client_account_page"))
        return view(*args, **kwargs)

    return decorated
