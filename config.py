import os
from dotenv import load_dotenv

# Find the .env file
basedir = os.path.abspath(os.path.dirname(__file__))

# --- THIS IS THE FIX ---
# Load the .env file *before* the Config class is defined.
load_dotenv(os.path.join(basedir, '.env'))
# --- END FIX ---

UPLOAD_FOLDER = os.path.join(basedir, 'app', 'static', 'uploads')

class Config:
    """Set Flask configuration variables from .env file."""

    # General Config
    # Now, when this line runs, os.environ.get() will find the loaded variable.
    FLASK_ENV = os.environ.get('FLASK_ENV')
    SECRET_KEY = os.environ.get('SECRET_KEY')

    # This was your edit for the email links, ensure it's here
    # (You should add SERVER_NAME to your .env file)
    SERVER_NAME = os.environ.get('SERVER_NAME') # e.g., '192.168.1.10:5000'

    UPLOAD_FOLDER = UPLOAD_FOLDER
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- ADD THESE LINES for Flask-Mail ---
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    # Also load email credentials from the .env file
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')

    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_USERNAME')