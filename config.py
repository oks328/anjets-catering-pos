import os
from dotenv import load_dotenv

# Find the .env file
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

UPLOAD_FOLDER = os.path.join(basedir, 'app', 'static', 'uploads')

class Config:
    """Set Flask configuration variables from .env file."""

    # General Config
    FLASK_ENV = os.environ.get('FLASK_ENV')

    SECRET_KEY = os.environ.get('SECRET_KEY')

    UPLOAD_FOLDER = UPLOAD_FOLDER
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ... (your existing SECRET_KEY and SQLALCHEMY settings) ...
    
    # --- ADD THESE LINES for Flask-Mail ---
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = 'khianvivar@gmail.com'  # <-- REPLACE with your full email
    MAIL_PASSWORD = 'mrnj qyok llsa pgru' # <-- REPLACE with your 16-digit App Password