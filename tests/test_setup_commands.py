from app import db
from app.models import Product, User


def test_create_admin_hashes_password(app):
    result = app.test_cli_runner().invoke(
        args=["create-admin", "--username", "manager"], input="StrongPassword1!\nStrongPassword1!\n"
    )
    assert result.exit_code == 0, result.output
    user = User.query.filter_by(username="manager").one()
    assert user.role == "Admin"
    assert user.password_hash != "StrongPassword1!"
    assert user.check_password("StrongPassword1!")


def test_create_admin_does_not_replace_user(app):
    user = db.session.get(User, 1)
    original_hash = user.password_hash
    result = app.test_cli_runner().invoke(
        args=["create-admin", "--username", user.username],
        input="StrongPassword1!\nStrongPassword1!\n",
    )
    assert result.exit_code != 0
    db.session.refresh(user)
    assert user.password_hash == original_hash


def test_create_admin_rejects_weak_password(app):
    result = app.test_cli_runner().invoke(
        args=["create-admin", "--username", "manager"], input="short\nshort\n"
    )
    assert result.exit_code != 0
    assert User.query.filter_by(username="manager").first() is None


def test_demo_menu_is_idempotent(app):
    runner = app.test_cli_runner()
    for _ in range(2):
        result = runner.invoke(args=["seed-demo"])
        assert result.exit_code == 0, result.output
    assert Product.query.count() == 3


def test_demo_seed_refuses_production(app, monkeypatch):
    monkeypatch.setitem(app.config, "APP_ENV", "production")
    result = app.test_cli_runner().invoke(args=["seed-demo"])
    assert result.exit_code != 0
    assert Product.query.count() == 1
