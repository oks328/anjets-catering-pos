"""Track completed sales and OAuth-only accounts

Revision ID: aac3c6110732
Revises: 1827077f1af9
Create Date: 2026-11-18 19:14:08.827317

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'aac3c6110732'
down_revision = '1827077f1af9'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    customers = sa.table('Customers', sa.column('email', sa.String()),
                         sa.column('password_hash', sa.String()))
    normalized = sa.func.lower(sa.func.trim(customers.c.email))
    duplicates = connection.execute(sa.select(normalized).group_by(normalized).having(sa.func.count() > 1)).first()
    if duplicates:
        raise RuntimeError('Resolve duplicate normalized emails before running this migration; accounts were not merged.')
    with op.batch_alter_table('Customers', schema=None) as batch_op:
        batch_op.alter_column('password_hash',
               existing_type=sa.VARCHAR(length=255),
               nullable=True)
    connection.execute(customers.update().values(email=normalized))
    connection.execute(customers.update().where(
        customers.c.password_hash == 'google_oauth_user_placeholder'
    ).values(password_hash=None))

    with op.batch_alter_table('Orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('completed_at', sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f('ix_Orders_completed_at'), ['completed_at'], unique=False)
    # Historical records have no completion timestamp; retain their original order date
    # as an approximation. Unpaid completed orders remain excluded from sales reports.
    orders = sa.table('Orders', sa.column('status', sa.String()),
                      sa.column('completed_at', sa.DateTime()), sa.column('order_date', sa.DateTime()))
    connection.execute(orders.update().where(orders.c.status == 'Completed').values(completed_at=orders.c.order_date))


def downgrade():
    with op.batch_alter_table('Orders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_Orders_completed_at'))
        batch_op.drop_column('completed_at')

    customers = sa.table('Customers', sa.column('password_hash', sa.String()))
    op.get_bind().execute(customers.update().where(customers.c.password_hash.is_(None)).values(
        password_hash='google_oauth_user_placeholder'))
    with op.batch_alter_table('Customers', schema=None) as batch_op:
        batch_op.alter_column('password_hash',
               existing_type=sa.VARCHAR(length=255),
               nullable=False)
