import hmac
import os

from flask import Flask, abort, request
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, current_user
from flask_mail import Mail
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

from config import Config

db = SQLAlchemy()
csrf = CSRFProtect()
migrate = Migrate()

bcrypt = Bcrypt()
login_manager = LoginManager()
login_manager.login_view = "admin_login"
login_manager.login_message_category = "info"

mail = Mail()


def create_app(config_class=Config):
    """Create and configure the Flask app."""

    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)
    from .auth import (
        credential_signature,
        validate_admin_session,
        validate_customer_session,
    )
    from .auth_limits import enforce_auth_limits

    app.before_request(validate_customer_session)
    app.before_request(validate_admin_session)
    app.before_request(enforce_auth_limits)

    @app.before_request
    def protect_private_uploads():
        if request.endpoint == "static":
            filename = (request.view_args or {}).get("filename", "")
            parts = filename.replace("\\", "/").split("/")
            if any(part.endswith((".", " ")) or ":" in part or "\x00" in part for part in parts):
                abort(404)
            normalized = os.path.normpath(filename).replace("\\", "/").lower().lstrip("/")
            if normalized.startswith("uploads/") and not normalized.startswith("uploads/products/"):
                abort(404)

    @app.before_request
    def protect_admin_routes():
        endpoint = request.endpoint or ""
        if (
            endpoint.startswith("admin_")
            and endpoint not in ("admin_login", "admin_logout")
            and current_user.is_authenticated
            and current_user.role != "Admin"
        ):
            abort(403)

    with app.app_context():
        from . import (
            models,
            oauth_routes,  # Import custom OAuth routes
            routes,
        )

        routes.register_routes(app)
        oauth_routes.register_oauth_routes(app)
        from .profile_completion import register_profile_routes

        register_profile_routes(app)

        from .card_payment_routes import register_card_payment_routes

        register_card_payment_routes(app)
        from .commands import register_commands

        register_commands(app)

        @login_manager.user_loader
        def load_user(user_id):
            from flask import session

            try:
                user = db.session.get(models.User, int(user_id))
            except (ValueError, TypeError):
                return None
            proof = session.get("admin_auth_version", "")
            if (
                user
                and isinstance(proof, str)
                and hmac.compare_digest(proof, credential_signature(user))
            ):
                return user
            return None

        @app.shell_context_processor
        def make_shell_context():
            return {
                "db": db,
                "User": models.User,
                "Category": models.Category,
                "Product": models.Product,
                "ProductVariant": models.ProductVariant,
                "Voucher": models.Voucher,
                "Customer": models.Customer,
                "Order": models.Order,
                "OrderItem": models.OrderItem,
            }

    return app
