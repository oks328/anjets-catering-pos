from app import create_app


def test_each_application_registers_its_routes(app):
    class Settings:
        TESTING = True
        SECRET_KEY = "factory-test-only"
        SQLALCHEMY_DATABASE_URI = "sqlite://"
        MAIL_SUPPRESS_SEND = True

    second = create_app(Settings)
    assert second.test_client().get("/account").status_code == 200
    assert set(app.view_functions) == set(second.view_functions)
