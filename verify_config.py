"""Report configuration presence without exposing credential values."""

from config import Config


def configured(value):
    return bool(value and not str(value).startswith("your_"))


def main():
    secret = configured(Config.SECRET_KEY)
    print("SECRET_KEY: " + ("configured" if secret else "missing or placeholder"))
    print("Database: " + ("configured" if Config.SQLALCHEMY_DATABASE_URI else "missing"))
    google = configured(Config.GOOGLE_OAUTH_CLIENT_ID) and configured(
        Config.GOOGLE_OAUTH_CLIENT_SECRET
    )
    print("Google sign-in: " + ("configured" if google else "optional, not configured"))
    print(
        "Email delivery: "
        + ("suppressed for local testing" if Config.MAIL_SUPPRESS_SEND else "enabled")
    )
    return 0 if secret else 1


if __name__ == "__main__":
    raise SystemExit(main())
