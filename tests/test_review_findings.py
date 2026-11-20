from pathlib import Path

import pytest

from app import db
from app.models import Order, ProductVariant


@pytest.mark.parametrize("folder", ["uploads.", "uploads ", "uploads::$INDEX_ALLOCATION"])
def test_windows_static_aliases_cannot_expose_documents(client, tmp_path, monkeypatch, folder):
    monkeypatch.setattr(client.application, "static_folder", str(tmp_path))
    path = Path(tmp_path) / "uploads" / "ids" / "document.txt"
    path.parent.mkdir(parents=True)
    path.write_text("private synthetic document")
    assert client.get(f"/static/{folder}/ids/document.txt").status_code == 404


def test_review_uses_current_menu_price(checkout):
    db.session.get(ProductVariant, 1).price = 200
    db.session.commit()
    html = checkout.get("/checkout").get_data(as_text=True)
    assert "₱224.00" in html
    assert "₱112.00" not in html


def test_changed_price_requires_reconfirmation(checkout, csrf):
    assert checkout.get("/checkout").status_code == 200
    db.session.get(ProductVariant, 1).price = 200
    db.session.commit()
    response = checkout.post(
        "/checkout/place_order", data={"csrf_token": csrf, "checkout_token": "a" * 64}
    )
    assert response.status_code == 409
    assert Order.query.count() == 0


def test_changed_gcash_amount_invalidates_proof(checkout, csrf):
    import io
    from datetime import date, timedelta

    from PIL import Image

    response = checkout.post(
        "/checkout/save_options",
        data={
            "csrf_token": csrf,
            "event_date": (date.today() + timedelta(days=10)).isoformat(),
            "event_time": "12:00",
            "order_type": "Pickup",
            "payment_method": "GCash",
        },
    )
    assert response.location.endswith("/checkout/gcash/upload")
    picture = io.BytesIO()
    Image.new("RGB", (2, 2)).save(picture, format="PNG")
    picture.seek(0)
    checkout.post(
        "/checkout/gcash/upload",
        data={
            "csrf_token": csrf,
            "reference_number": "1234567890123",
            "receipt_image": (picture, "proof.png"),
        },
    )
    assert checkout.get("/checkout").status_code == 200
    db.session.get(ProductVariant, 1).price = 200
    db.session.commit()
    response = checkout.post(
        "/checkout/place_order", data={"csrf_token": csrf, "checkout_token": "a" * 64}
    )
    assert response.status_code == 409
    with checkout.session_transaction() as session:
        assert "gcash_image_file" not in session
        assert "gcash_quote" not in session
    assert Order.query.count() == 0


def test_config_verifier_does_not_print_credentials():
    import os
    import subprocess
    import sys

    env = dict(
        os.environ,
        GOOGLE_OAUTH_CLIENT_ID="DO_NOT_PRINT_CLIENT",
        GOOGLE_OAUTH_CLIENT_SECRET="DO_NOT_PRINT_SECRET",
    )
    result = subprocess.run(
        [sys.executable, "verify_config.py"], env=env, capture_output=True, text=True
    )
    assert "DO_NO" not in result.stdout
