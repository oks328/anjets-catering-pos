from types import SimpleNamespace

import pytest

from app import db
from app.models import Customer


@pytest.fixture
def google_sdk(monkeypatch, app):
    import requests
    from google_auth_oauthlib.flow import Flow

    data = {
        "id": "google-123",
        "email": "new@example.com",
        "name": "Google User",
        "verified_email": True,
    }
    seen = {}

    class FakeFlow:
        credentials = SimpleNamespace(token="test-access-token")
        code_verifier = "test-pkce-verifier"

        def authorization_url(self, **kwargs):
            return "https://accounts.google.com/test", "new-state"

        def fetch_token(self, **kwargs):
            pass

    def from_config(config, **kwargs):
        seen["config"] = config
        seen["kwargs"] = kwargs
        return FakeFlow()

    def get_info(*args, **kwargs):
        seen["userinfo_kwargs"] = kwargs
        return SimpleNamespace(ok=True, json=lambda: data)

    monkeypatch.setattr(Flow, "from_client_config", from_config)
    monkeypatch.setattr(requests, "get", get_info)
    monkeypatch.setitem(app.config, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setitem(app.config, "GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setitem(
        app.config, "GOOGLE_OAUTH_REDIRECT_URI", "https://catering.example/auth/google/callback"
    )
    return data, seen


def callback(client):
    with client.session_transaction() as session:
        session["oauth_state"] = "test-state"
        session["oauth_redirect_uri"] = "https://catering.example/auth/google/callback"
        session["oauth_code_verifier"] = "test-pkce-verifier"
    return client.get("/auth/google/callback?state=test-state&code=test-code")


def test_google_uses_configured_redirect(client, google_sdk):
    client.get("/auth/google")
    _, seen = google_sdk
    assert seen["config"]["web"]["redirect_uris"] == [
        "https://catering.example/auth/google/callback"
    ]


def test_google_account_has_no_local_password(client, google_sdk):
    assert callback(client).location.endswith("/complete_profile")
    customer = Customer.query.filter_by(google_id="google-123").one()
    assert customer.password_hash is None
    _, seen = google_sdk
    assert seen["userinfo_kwargs"]["timeout"] == 10
    assert seen["kwargs"]["code_verifier"] == "test-pkce-verifier"


@pytest.mark.parametrize("verified", [False, None, "false"])
def test_unverified_google_email_cannot_link_account(client, google_sdk, verified):
    data, _ = google_sdk
    data.update(email="customer@example.com", verified_email=verified)
    callback(client)
    assert db.session.get(Customer, 1).google_id is None
    with client.session_transaction() as session:
        assert "customer_id" not in session


def test_google_does_not_replace_existing_identity(client, google_sdk):
    customer = db.session.get(Customer, 1)
    customer.google_id = "different-google-account"
    db.session.commit()
    google_sdk[0]["email"] = customer.email
    callback(client)
    db.session.refresh(customer)
    assert customer.google_id == "different-google-account"


def test_google_consumes_failed_state(client, google_sdk, monkeypatch):
    import requests

    def fail(*args, **kwargs):
        raise requests.RequestException("private-token-exchange-details")

    monkeypatch.setattr(requests, "get", fail)
    callback(client)
    with client.session_transaction() as session:
        assert "oauth_state" not in session
        assert "oauth_code_verifier" not in session
        assert "private-token-exchange-details" not in str(session.get("_flashes"))


def test_legacy_google_route_redirects_to_supported_flow(client):
    response = client.get("/login/google/complete")
    assert response.location.endswith("/auth/google")
