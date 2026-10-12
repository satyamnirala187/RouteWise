"""initial schema: users, riders, sessions, login throttling, imports, rounds, orders, assignments

Reviewed by hand after autogeneration. Order statuses are constrained to exactly
Pending/Postponed/Completed; a resolved location must carry coordinates.

Revision ID: 0001
Revises: 
Create Date: 2026-10-13 01:08:51.630828
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('login_failures',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('username_key', sa.String(length=64), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_login_failures_at'), 'login_failures', ['at'], unique=False)
    op.create_index(op.f('ix_login_failures_ip'), 'login_failures', ['ip'], unique=False)
    op.create_index(op.f('ix_login_failures_username_key'), 'login_failures', ['username_key'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('admin','rider')", name='ck_users_role'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username')
    )
    op.create_table('delivery_rounds',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('riders',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('display_name', sa.String(length=100), nullable=False),
    sa.Column('vehicle', sa.String(length=16), nullable=True),
    sa.CheckConstraint("vehicle IS NULL OR vehicle IN ('scooter','bike')", name='ck_riders_vehicle'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_table('sessions',
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('csrf_token', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('token_hash')
    )
    op.create_index(op.f('ix_sessions_user_id'), 'sessions', ['user_id'], unique=False)
    op.create_table('import_batches',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('rows', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('round_id', sa.UUID(), nullable=True),
    sa.CheckConstraint("state IN ('preview','committed','discarded')", name='ck_import_state'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['round_id'], ['delivery_rounds.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('orders',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('order_code', sa.String(length=32), nullable=False),
    sa.Column('round_id', sa.UUID(), nullable=False),
    sa.Column('source_row', sa.Integer(), nullable=False),
    sa.Column('customer_name', sa.String(length=200), nullable=False),
    sa.Column('product', sa.String(length=500), nullable=False),
    sa.Column('contact', sa.String(length=40), nullable=False),
    sa.Column('instructions', sa.Text(), nullable=True),
    sa.Column('location_link', sa.String(length=2048), nullable=False),
    sa.Column('location_state', sa.String(length=20), nullable=False),
    sa.Column('location_source', sa.String(length=20), nullable=True),
    sa.Column('location_note', sa.String(length=300), nullable=True),
    sa.Column('lat', sa.Double(), nullable=True),
    sa.Column('lng', sa.Double(), nullable=True),
    sa.Column('building_id', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=16), server_default=sa.text("'Pending'"), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(location_state = 'resolved') = (lat IS NOT NULL AND lng IS NOT NULL)", name='ck_orders_resolved_has_coords'),
    sa.CheckConstraint("location_source IS NULL OR location_source IN ('place_pin','query','geo_uri','short_link','manual_pin')", name='ck_orders_location_source'),
    sa.CheckConstraint("location_state IN ('resolved','needs_correction')", name='ck_orders_location_state'),
    sa.CheckConstraint("status IN ('Pending','Postponed','Completed')", name='ck_orders_status'),
    sa.CheckConstraint('lat IS NULL OR (lat BETWEEN -90 AND 90)', name='ck_orders_lat'),
    sa.CheckConstraint('lng IS NULL OR (lng BETWEEN -180 AND 180)', name='ck_orders_lng'),
    sa.ForeignKeyConstraint(['round_id'], ['delivery_rounds.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('order_code', name='uq_orders_order_code')
    )
    op.create_index(op.f('ix_orders_round_id'), 'orders', ['round_id'], unique=False)
    op.create_table('assignments',
    sa.Column('order_id', sa.UUID(), nullable=False),
    sa.Column('rider_id', sa.UUID(), nullable=False),
    sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['rider_id'], ['riders.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('order_id')
    )
    op.create_index(op.f('ix_assignments_rider_id'), 'assignments', ['rider_id'], unique=False)
    # Human-readable, unique order codes (RW-001001, ...); see routewise_api.orders.next_order_code.
    op.execute("CREATE SEQUENCE order_code_seq START WITH 1001")


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS order_code_seq")
    op.drop_index(op.f('ix_assignments_rider_id'), table_name='assignments')
    op.drop_table('assignments')
    op.drop_index(op.f('ix_orders_round_id'), table_name='orders')
    op.drop_table('orders')
    op.drop_table('import_batches')
    op.drop_index(op.f('ix_sessions_user_id'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_table('riders')
    op.drop_table('delivery_rounds')
    op.drop_table('users')
    op.drop_index(op.f('ix_login_failures_username_key'), table_name='login_failures')
    op.drop_index(op.f('ix_login_failures_ip'), table_name='login_failures')
    op.drop_index(op.f('ix_login_failures_at'), table_name='login_failures')
    op.drop_table('login_failures')
