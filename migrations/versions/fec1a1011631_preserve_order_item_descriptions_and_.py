"""Preserve order item descriptions and validate menu values

Revision ID: fec1a1011631
Revises: aac3c6110732
Create Date: 2026-11-18 19:45:48.887357

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fec1a1011631'
down_revision = 'aac3c6110732'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    variants = sa.table('Product_Variants', sa.column('variant_id', sa.Integer()),
                        sa.column('price', sa.Numeric(10, 2)), sa.column('size_name', sa.String()))
    items = sa.table('Order_Items', sa.column('order_item_id', sa.Integer()),
                     sa.column('quantity', sa.Integer()), sa.column('product_id', sa.Integer()),
                     sa.column('variant_id', sa.Integer()), sa.column('product_name_snapshot', sa.String()),
                     sa.column('variant_name_snapshot', sa.String()))
    invalid_price = connection.execute(sa.select(variants.c.variant_id).where(sa.or_(
        variants.c.price <= 0, variants.c.price > 99999999.99,
        variants.c.price != sa.func.round(variants.c.price, 2),
    )).limit(1)).first()
    invalid_quantity = connection.execute(sa.select(items.c.order_item_id).where(sa.or_(
        items.c.quantity <= 0, items.c.quantity > 2147483647,
        items.c.quantity != sa.cast(items.c.quantity, sa.BigInteger),
    )).limit(1)).first()
    if invalid_price or invalid_quantity:
        raise RuntimeError('Resolve invalid legacy menu/order data before upgrading; no records were deleted or corrected.')
    with op.batch_alter_table('Order_Items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('product_name_snapshot', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('variant_name_snapshot', sa.String(length=50), nullable=True))
        batch_op.create_check_constraint('ck_order_items_quantity_range', 'quantity > 0 AND quantity <= 2147483647')

    products = sa.table('Products', sa.column('product_id', sa.Integer()), sa.column('name', sa.String()))
    product_name = sa.select(products.c.name).where(products.c.product_id == items.c.product_id).scalar_subquery()
    variant_name = sa.select(variants.c.size_name).where(variants.c.variant_id == items.c.variant_id).scalar_subquery()
    connection.execute(items.update().values(
        product_name_snapshot=sa.func.coalesce(product_name, 'Unavailable product'),
        variant_name_snapshot=sa.func.coalesce(variant_name, 'Unavailable variant'),
    ))
    with op.batch_alter_table('Product_Variants', schema=None) as batch_op:
        batch_op.create_check_constraint('ck_product_variants_price_range', 'price > 0 AND price <= 99999999.99')


def downgrade():
    with op.batch_alter_table('Product_Variants', schema=None) as batch_op:
        batch_op.drop_constraint('ck_product_variants_price_range', type_='check')
    with op.batch_alter_table('Order_Items', schema=None) as batch_op:
        batch_op.drop_constraint('ck_order_items_quantity_range', type_='check')
        batch_op.drop_column('variant_name_snapshot')
        batch_op.drop_column('product_name_snapshot')
