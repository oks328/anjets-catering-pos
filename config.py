import os

from dotenv import load_dotenv

# Find the .env file
basedir = os.path.abspath(os.path.dirname(__file__))

# Load the .env file *before* the Config class is defined.
load_dotenv(os.path.join(basedir, ".env"))

UPLOAD_FOLDER = os.path.join(basedir, "app", "static", "uploads")


class Config:
    """Set Flask configuration variables from .env file."""

    # General Config
    # Now, when this line runs, os.environ.get() will find the loaded variable.
    FLASK_ENV = os.environ.get("FLASK_ENV")
    SECRET_KEY = os.environ.get("SECRET_KEY")

    GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    GOOGLE_OAUTH_REDIRECT_URI = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI")
    BUSINESS_TIMEZONE = os.environ.get("BUSINESS_TIMEZONE", "Asia/Manila")

    # This was your edit for the email links, ensure it's here
    # (You should add SERVER_NAME to your .env file)
    SERVER_NAME = os.environ.get("SERVER_NAME")  # e.g., '192.168.1.10:5000'

    UPLOAD_FOLDER = UPLOAD_FOLDER
    PRIVATE_UPLOAD_FOLDER = os.path.join(basedir, "private_uploads")
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"

    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or "sqlite:///site.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- ADD THESE LINES for Flask-Mail ---
    MAIL_SERVER = "smtp.gmail.com"
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    # Also load email credentials from the .env file
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")

    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_USERNAME")
    MAIL_SUPPRESS_SEND = os.environ.get("MAIL_SUPPRESS_SEND", "0") == "1"
    APP_ENV = os.environ.get("APP_ENV", "development")
    AUTH_LOGIN_ACCOUNT_LIMIT = 5
    AUTH_LOGIN_IP_LIMIT = 30
    AUTH_LOGIN_WINDOW_SECONDS = 900
    AUTH_RESET_ACCOUNT_LIMIT = 3
    AUTH_RESET_IP_LIMIT = 10
    AUTH_RESET_WINDOW_SECONDS = 3600
