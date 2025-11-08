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