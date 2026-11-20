import os
import subprocess
import sys
from datetime import datetime

import pytest
from sqlalchemy import MetaData, create_engine, func, select


@pytest.mark.parametrize("invalid", [None, "price", "quantity"])
def test_history_migration_preserves_legacy_items(tmp_path, invalid):
    uri = "sqlite:///" + (tmp_path / "history.db").as_posix()
    env = dict(os.environ, DATABASE_URL=uri, SECRET_KEY="test-history-migration")

    def upgrade(revision):
        return subprocess.run(
            [sys.executable, "-m", "flask", "--app", "run", "db", "upgrade", revision],
            env=env,
            capture_output=True,
            text=True,
        )

    assert upgrade("aac3c6110732").returncode == 0
    engine = create_engine(uri)
    metadata = MetaData()
    metadata.reflect(engine)
    with engine.begin() as connection:
        connection.execute(
            metadata.tables["Customers"]
            .insert()
            .values(
                customer_id=1,
                name="Legacy",
                email="legacy@example.com",
                password_hash=None,
                registration_date=datetime(2026, 1, 1),
                is_verified_discount=False,
            )
        )
        connection.execute(
            metadata.tables["Categories"]
            .insert()
            .values(category_id=1, name="Chicken", is_active=True)
        )
        connection.execute(
            metadata.tables["Products"]
            .insert()
            .values(
                product_id=1,
                category_id=1,
                name="Original Dish",
                has_variants=False,
                is_active=True,
                image_file="default.jpg",
            )
        )
        connection.execute(
            metadata.tables["Product_Variants"]
            .insert()
            .values(
                variant_id=1,
                product_id=1,
                size_name="Original Size",
                price=0 if invalid == "price" else 100,
            )
        )
        connection.execute(
            metadata.tables["Orders"]
            .insert()
            .values(
                order_id=1,
                customer_id=1,
                order_date=datetime(2026, 1, 2),
                total_amount=100,
                final_amount=112,
                discount_amount=0,
                delivery_fee=0,
                vat_amount=12,
                status="Approved",
                payment_method="COD/COP",
                payment_status="Pending",
                order_type="Pickup",
            )
        )
        connection.execute(
            metadata.tables["Order_Items"]
            .insert()
            .values(
                order_id=1,
                product_id=1,
                variant_id=1,
                quantity=0 if invalid == "quantity" else 1,
                price_per_item=100,
            )
        )
    result = upgrade("head")
    try:
        if invalid:
            assert result.returncode != 0
            assert "invalid legacy menu/order data" in result.stderr
        else:
            assert result.returncode == 0, result.stdout + result.stderr
            metadata = MetaData()
            metadata.reflect(engine)
            items = metadata.tables["Order_Items"]
            assert "product_name_snapshot" in items.c
            with engine.connect() as connection:
                item = connection.execute(select(items)).mappings().one()
            assert item["product_name_snapshot"] == "Original Dish"
            assert item["variant_name_snapshot"] == "Original Size"
        with engine.connect() as connection:
            assert (
                connection.scalar(select(func.count()).select_from(metadata.tables["Order_Items"]))
                == 1
            )
    finally:
        engine.dispose()
