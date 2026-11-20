"""Keep old card-checkout links working without collecting card data."""

from flask import flash, redirect, url_for

from app.auth import customer_login_required


def register_card_payment_routes(app):
    """Redirect to supported methods until a payment provider is integrated."""

    @app.route("/checkout/card/payment", methods=["GET", "POST"])
    @customer_login_required
    def client_card_payment():
        flash("Card payments are not available yet. Please choose GCash or cash.", "info")
        return redirect(url_for("client_checkout_options"))
