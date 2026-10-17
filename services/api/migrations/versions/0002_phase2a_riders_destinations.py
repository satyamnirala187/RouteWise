"""phase 2A: depots, per-round rider configuration, rider destinations and confirmations

Written by hand and checked against the models (no autogenerate diff). Adds the round-level
planning-input version and a rider profile version. Home/Custom destination coordinates live
only in rider_endpoints and require a location exactly when the kind is home or custom.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('delivery_rounds', sa.Column('input_version', sa.Integer(), server_default=sa.text('1'), nullable=False))
    op.create_check_constraint('ck_rounds_input_version', 'delivery_rounds', 'input_version >= 1')
    op.add_column('riders', sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False))

    op.create_table('depots',
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('label', sa.String(length=100), nullable=False),
    sa.Column('lat', sa.Double(), nullable=False),
    sa.Column('lng', sa.Double(), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('office','warehouse')", name='ck_depots_kind'),
    sa.CheckConstraint('lat BETWEEN -90 AND 90', name='ck_depots_lat'),
    sa.CheckConstraint('lng BETWEEN -180 AND 180', name='ck_depots_lng'),
    sa.CheckConstraint('length(btrim(label)) > 0', name='ck_depots_label'),
    sa.CheckConstraint('version >= 1', name='ck_depots_version'),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('kind')
    )
    op.create_table('round_riders',
    sa.Column('round_id', sa.UUID(), nullable=False),
    sa.Column('rider_id', sa.UUID(), nullable=False),
    sa.Column('participating', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('vehicle', sa.String(length=16), nullable=False),
    sa.Column('capacity', sa.Integer(), nullable=False),
    sa.Column('start_kind', sa.String(length=16), nullable=False),
    sa.Column('config_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('confirmed_version', sa.Integer(), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("vehicle IN ('scooter','bike')", name='ck_round_riders_vehicle'),
    sa.CheckConstraint("start_kind IN ('office','warehouse')", name='ck_round_riders_start'),
    sa.CheckConstraint('capacity BETWEEN 1 AND 1000', name='ck_round_riders_capacity'),
    sa.CheckConstraint('config_version >= 1', name='ck_round_riders_config_version'),
    sa.CheckConstraint('(confirmed_version IS NULL) = (confirmed_at IS NULL)', name='ck_round_riders_confirmed_pair'),
    sa.CheckConstraint('confirmed_version IS NULL OR confirmed_version BETWEEN 1 AND config_version',
                       name='ck_round_riders_confirmed_version'),
    sa.ForeignKeyConstraint(['round_id'], ['delivery_rounds.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['rider_id'], ['riders.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('round_id', 'rider_id')
    )
    op.create_index(op.f('ix_round_riders_rider_id'), 'round_riders', ['rider_id'], unique=False)
    op.create_table('rider_endpoints',
    sa.Column('round_id', sa.UUID(), nullable=False),
    sa.Column('rider_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('lat', sa.Double(), nullable=True),
    sa.Column('lng', sa.Double(), nullable=True),
    sa.Column('location_source', sa.String(length=20), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('office','warehouse','home','last_stop','custom')", name='ck_rider_endpoints_kind'),
    sa.CheckConstraint("(kind IN ('home','custom')) = (lat IS NOT NULL AND lng IS NOT NULL)",
                       name='ck_rider_endpoints_location_iff_home_custom'),
    sa.CheckConstraint('(lat IS NULL) = (lng IS NULL)', name='ck_rider_endpoints_coord_pair'),
    sa.CheckConstraint('(location_source IS NULL) = (lat IS NULL)', name='ck_rider_endpoints_source'),
    sa.CheckConstraint("location_source IS NULL OR location_source IN ('place_pin','query','geo_uri','short_link','manual_pin')",
                       name='ck_rider_endpoints_source_values'),
    sa.CheckConstraint('lat IS NULL OR (lat BETWEEN -90 AND 90)', name='ck_rider_endpoints_lat'),
    sa.CheckConstraint('lng IS NULL OR (lng BETWEEN -180 AND 180)', name='ck_rider_endpoints_lng'),
    sa.ForeignKeyConstraint(['round_id', 'rider_id'], ['round_riders.round_id', 'round_riders.rider_id'],
                            name='fk_rider_endpoints_round_rider', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('round_id', 'rider_id')
    )


def downgrade() -> None:
    op.drop_table('rider_endpoints')
    op.drop_index(op.f('ix_round_riders_rider_id'), table_name='round_riders')
    op.drop_table('round_riders')
    op.drop_table('depots')
    op.drop_column('riders', 'version')
    op.drop_constraint('ck_rounds_input_version', 'delivery_rounds', type_='check')
    op.drop_column('delivery_rounds', 'input_version')
