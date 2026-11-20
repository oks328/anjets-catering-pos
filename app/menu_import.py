"""Validate complete CSV rows before adding products or sizes to the transaction."""

import csv
import io

from sqlalchemy import func

from app import db
from app.models import Category, Product, ProductVariant
from app.pricing import money


def import_menu_csv(stream):
    text = stream.read().decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    created = {}
    sizes = {}
    errors = []
    variant_count = 0
    first_record = True
    for row_number, row in enumerate(reader, 1):
        if not row or not any(value.strip() for value in row):
            continue
        row = [value.strip() for value in row]
        if first_record:
            first_record = False
            header = [value.lower().replace("_", " ") for value in row]
            if (
                len(header) == 6
                and header[0] in ("category", "category name")
                and header[1] in ("name", "product name")
            ):
                continue
        try:
            if len(row) != 6:
                raise ValueError("Expected exactly six columns.")
            category_name, name, description, variant_flag, price_text, size = row
            if not 3 <= len(name) <= 255 or not 1 <= len(size) <= 50:
                raise ValueError(
                    "Product name must be 3–255 characters and size must be 1–50 characters."
                )
            if variant_flag.lower() not in ("true", "false"):
                raise ValueError("Has Variants must be True or False.")
            has_variants = variant_flag.lower() == "true"
            price = money(price_text, positive=True)
            category = Category.query.filter(
                func.lower(Category.name) == category_name.lower(),
                Category.is_active.is_(True),
            ).first()
            if not category:
                raise ValueError("Category was not found or is inactive.")
            key = name.casefold()
            product = created.get(key)
            if product:
                if (
                    not has_variants
                    or not product.has_variants
                    or product.category_id != category.category_id
                ):
                    raise ValueError(
                        "Repeated product must use the same category and Has Variants=True."
                    )
            elif Product.query.filter(func.lower(Product.name) == name.lower()).first():
                raise ValueError("Product already exists; existing products are not overwritten.")
            if size.casefold() in sizes.get(key, set()):
                raise ValueError("This size is already present in the import.")
        except ValueError as error:
            errors.append(f"Row {row_number}: {error}")
            continue
        if product is None:
            product = Product(
                name=name,
                description=description,
                category_id=category.category_id,
                has_variants=has_variants,
            )
            db.session.add(product)
            created[key] = product
            sizes[key] = set()
        db.session.add(ProductVariant(product=product, size_name=size, price=price))
        sizes[key].add(size.casefold())
        variant_count += 1
    return len(created), variant_count, errors
