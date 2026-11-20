"""Explicit local setup commands; never replace existing users or menu records."""

from decimal import Decimal
from types import SimpleNamespace

import click
from wtforms.validators import ValidationError

from app import db
from app.forms import password_complexity
from app.models import Category, Product, ProductVariant, User


def register_commands(app):
    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.password_option()
    def create_admin(username, password):
        """Create a new administrator using a hidden, confirmed password prompt."""
        username = username.strip()
        if not 4 <= len(username) <= 100:
            raise click.ClickException("Username must be 4–100 characters.")
        if User.query.filter_by(username=username).first():
            raise click.ClickException("That user already exists; no changes were made.")
        try:
            password_complexity(None, SimpleNamespace(data=password))
        except ValidationError as error:
            raise click.ClickException(str(error)) from None
        user = User(username=username, role="Admin")
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise click.ClickException("Could not create the administrator.") from None
        click.echo(f"Administrator {username} created.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """Add two example trays to a development SQLite database."""
        if app.config.get("APP_ENV") != "development" or db.engine.dialect.name != "sqlite":
            raise click.ClickException(
                "Demo data is only available for development SQLite databases."
            )
        added = 0
        for category_name, name, price in (
            ("Chicken", "Demo Chicken Tray", "750.00"),
            ("Pork", "Demo Pork Tray", "850.00"),
        ):
            if Product.query.filter_by(name=name).first():
                continue
            category = Category.query.filter_by(name=category_name).first()
            if category is None:
                category = Category(name=category_name)
                db.session.add(category)
            product = Product(
                name=name,
                category=category,
                description="Sample menu item for local testing.",
                image_file="product-placeholder.svg",
            )
            db.session.add(
                ProductVariant(product=product, size_name="Regular", price=Decimal(price))
            )
            added += 1
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise click.ClickException("Could not load demo menu data.") from None
        click.echo(f"Added {added} demo products; existing records were preserved.")
