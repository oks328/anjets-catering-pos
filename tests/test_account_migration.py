import os
import subprocess
import sys
from datetime import datetime

import pytest
from sqlalchemy import MetaData, create_engine, select


@pytest.mark.parametrize("duplicate", [False, True])
def test_legacy_account_migration(tmp_path, duplicate):
    uri = "sqlite:///" + (tmp_path / "legacy.db").as_posix()
    env = dict(os.environ, DATABASE_URL=uri, SECRET_KEY="test-migration-only")

    def migrate(revision):
        return subprocess.run(
            [sys.executable, "-m", "flask", "--app", "run", "db", "upgrade", revision],
            env=env,
            capture_output=True,
            text=True,
        )

    assert migrate("1827077f1af9").returncode == 0
    engine = create_engine(uri)
    metadata = MetaData()
    metadata.reflect(engine)
    customers = metadata.tables["Customers"]
    orders = metadata.tables["Orders"]
    with engine.begin() as connection:
        connection.execute(
            customers.insert().values(
                customer_id=1,
                name="Legacy Google User",
                email=" LEGACY@EXAMPLE.COM ",
                password_hash="google_oauth_user_placeholder",
                registration_date=datetime(2026, 1, 1),
                is_verified_discount=False,
            )
        )
        if duplicate:
            connection.execute(
                customers.insert().values(
                    customer_id=2,
                    name="Other User",
                    email="legacy@example.com",
                    password_hash="old-hash",
                    registration_date=datetime(2026, 1, 1),
                    is_verified_discount=False,
                )
            )
        connection.execute(
            orders.insert().values(
                customer_id=1,
                order_date=datetime(2026, 1, 2),
                total_amount=100,
                final_amount=112,
                discount_amount=0,
                delivery_fee=0,
                vat_amount=12,
                status="Completed",
                payment_method="COD/COP",
                payment_status="Paid",
                order_type="Pickup",
            )
        )
    result = migrate("head")
    try:
        if duplicate:
            assert result.returncode != 0
            assert "duplicate normalized emails" in result.stderr
        else:
            assert result.returncode == 0, result.stdout + result.stderr
            metadata = MetaData()
            metadata.reflect(engine)
            with engine.connect() as connection:
                customer = connection.execute(select(metadata.tables["Customers"])).mappings().one()
                order = connection.execute(select(metadata.tables["Orders"])).mappings().one()
            assert customer["email"] == "legacy@example.com"
            assert customer["password_hash"] is None
            assert order["completed_at"] == datetime(2026, 1, 2)
    finally:
        engine.dispose()
