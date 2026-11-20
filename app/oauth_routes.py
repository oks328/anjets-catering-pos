"""Google sign-in with verified account linking and one-use OAuth state."""

import hmac
from urllib.parse import urlsplit

import requests
from flask import current_app as app
from flask import flash, redirect, request, session, url_for
from google_auth_oauthlib.flow import Flow

from app import db
from app.auth import sign_in_customer
from app.models import Customer

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


def google_flow(redirect_uri, state=None, code_verifier=None):
    return Flow.from_client_config(
        {
            "web": {
                "client_id": app.config["GOOGLE_OAUTH_CLIENT_ID"],
                "client_secret": app.config["GOOGLE_OAUTH_CLIENT_SECRET"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            },
        },
        scopes=SCOPES,
        state=state,
        code_verifier=code_verifier,
    )


def google_login():
    if not app.config.get("GOOGLE_OAUTH_CLIENT_ID") or not app.config.get(
        "GOOGLE_OAUTH_CLIENT_SECRET"
    ):
        flash("Google sign-in is not configured yet.", "info")
        return redirect(url_for("client_account_page"))
    redirect_uri = app.config.get("GOOGLE_OAUTH_REDIRECT_URI") or url_for(
        "google_callback", _external=True
    )
    parsed = urlsplit(redirect_uri)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
    ):
        flash("Google sign-in requires a valid HTTPS callback URL.", "danger")
        return redirect(url_for("client_account_page"))
    try:
        flow = google_flow(redirect_uri)
        flow.redirect_uri = redirect_uri
        authorization_url, state = flow.authorization_url(prompt="select_account")
        session["oauth_state"] = state
        session["oauth_redirect_uri"] = redirect_uri
        session["oauth_code_verifier"] = flow.code_verifier
        return redirect(authorization_url)
    except Exception:
        app.logger.exception("Could not initiate Google sign-in")
        flash("Google sign-in is unavailable. Please try again.", "danger")
        return redirect(url_for("client_account_page"))


def google_callback():
    state = session.pop("oauth_state", None)
    redirect_uri = session.pop("oauth_redirect_uri", None)
    code_verifier = session.pop("oauth_code_verifier", None)
    if (
        not state
        or not redirect_uri
        or not code_verifier
        or not hmac.compare_digest(state, request.args.get("state", ""))
    ):
        flash("Invalid sign-in request. Please try again.", "danger")
        return redirect(url_for("client_account_page"))
    try:
        flow = google_flow(redirect_uri, state=state, code_verifier=code_verifier)
        flow.redirect_uri = redirect_uri
        flow.fetch_token(authorization_response=request.url, timeout=10)
        response = requests.get(
            "https://www.googleapis.com/oauth2/v1/userinfo",
            headers={"Authorization": f"Bearer {flow.credentials.token}"},
            timeout=10,
        )
        if not response.ok:
            raise ValueError("User information unavailable")
        data = response.json()
        google_id = data.get("id")
        email = (data.get("email") or "").strip().lower()
        if not google_id or not email or data.get("verified_email") is not True:
            flash("Google must provide a verified email address to sign in.", "danger")
            return redirect(url_for("client_account_page"))
        customer = Customer.query.filter_by(google_id=google_id).first()
        if customer is None:
            customer = Customer.query.filter_by(email=email).first()
            if customer and customer.google_id and customer.google_id != google_id:
                flash(
                    "This email is linked to another Google account. Please contact support.",
                    "danger",
                )
                return redirect(url_for("client_account_page"))
            if customer is None:
                customer = Customer(
                    name=data.get("name") or "Customer",
                    email=email,
                    google_id=google_id,
                    password_hash=None,
                )
                db.session.add(customer)
            else:
                customer.google_id = google_id
            db.session.commit()
        sign_in_customer(customer)
        if not customer.contact_number or not customer.address or not customer.birthdate:
            return redirect(url_for("complete_profile"))
        return redirect(url_for("client_home", welcome="google"))
    except Exception:
        db.session.rollback()
        app.logger.exception("Google sign-in failed")
        flash("Could not sign in with Google. Please try again.", "danger")
        return redirect(url_for("client_account_page"))


def register_oauth_routes(app):
    """Register routes on each application instance."""
    app.add_url_rule("/auth/google", view_func=google_login)
    app.add_url_rule("/auth/google/callback", view_func=google_callback)
