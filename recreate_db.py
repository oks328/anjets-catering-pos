"""Compatibility launcher: apply versioned migrations without deleting data."""

from flask_migrate import upgrade

from app import create_app

app = create_app()

with app.app_context():
    upgrade()
    print("Database migrations applied successfully.")
