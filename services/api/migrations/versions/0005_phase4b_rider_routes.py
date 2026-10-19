"""phase 4B: rider route revisions layered on immutable round plans

- `round_riders.route_version`: rider-scoped route validity (a rider's own destination change).
- `plan_routes.rider_route_version`: the rider's route_version when the round plan was committed.
- `orders.completed_at` / `completed_by`: when and by whom an order became Completed. Orders that
  were Completed before this migration keep NULL ("time unknown"); no timestamp is invented.
- `planning_runs.scope` / `rider_id` / `base_plan_id` / `origin_kind`: a rider's own reroute runs in
  the same bounded worker. One active round run per round and one active rider run per rider.
- `route_revisions` / `revision_orders`: the rider's recalculated sequence. No position is stored.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-19
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE = "state IN ('queued','running')"


def upgrade() -> None:
    op.add_column('round_riders', sa.Column('route_version', sa.Integer(), server_default=sa.text('1'), nullable=False))
    op.create_check_constraint('ck_round_riders_route_version', 'round_riders', 'route_version >= 1')
    op.add_column('plan_routes', sa.Column('rider_route_version', sa.Integer(), server_default=sa.text('1'), nullable=False))

    op.add_column('orders', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('orders', sa.Column('completed_by', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_orders_completed_by', 'orders', 'users', ['completed_by'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_orders_completed_pair', 'orders', '(completed_at IS NULL) = (completed_by IS NULL)')
    op.create_check_constraint('ck_orders_completed_only_when_completed', 'orders',
                               "status = 'Completed' OR completed_at IS NULL")

    op.add_column('planning_runs', sa.Column('scope', sa.String(length=8), server_default=sa.text("'round'"), nullable=False))
    op.add_column('planning_runs', sa.Column('rider_id', sa.UUID(), nullable=True))
    op.add_column('planning_runs', sa.Column('base_plan_id', sa.UUID(), nullable=True))
    op.add_column('planning_runs', sa.Column('origin_kind', sa.String(length=24), nullable=True))
    op.create_foreign_key('fk_planning_runs_rider_id', 'planning_runs', 'riders', ['rider_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_planning_runs_base_plan_id', 'planning_runs', 'route_plans', ['base_plan_id'], ['id'],
                          ondelete='CASCADE')
    op.create_check_constraint('ck_planning_runs_scope', 'planning_runs', "scope IN ('round','rider')")
    op.create_check_constraint('ck_planning_runs_rider_scope', 'planning_runs', "(scope = 'rider') = (rider_id IS NOT NULL)")
    op.create_check_constraint('ck_planning_runs_rider_fields', 'planning_runs',
                               "scope = 'round' OR (base_plan_id IS NOT NULL AND origin_kind IS NOT NULL)")
    op.create_check_constraint('ck_planning_runs_origin_kind', 'planning_runs',
                               "origin_kind IS NULL OR origin_kind IN ('current_position','last_completed_stop','configured_start')")
    op.drop_index('uq_planning_runs_one_active', table_name='planning_runs', postgresql_where=sa.text(ACTIVE))
    op.create_index('uq_planning_runs_one_active_round', 'planning_runs', ['round_id'], unique=True,
                    postgresql_where=sa.text(f"{ACTIVE} AND scope = 'round'"))
    op.create_index('uq_planning_runs_one_active_rider', 'planning_runs', ['round_id', 'rider_id'], unique=True,
                    postgresql_where=sa.text(f"{ACTIVE} AND scope = 'rider'"))

    op.create_table(
        'route_revisions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('round_id', sa.UUID(), nullable=False),
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('rider_id', sa.UUID(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('is_current', sa.Boolean(), nullable=False),
        sa.Column('trigger', sa.String(length=16), nullable=False),
        sa.Column('origin_kind', sa.String(length=24), nullable=False),
        sa.Column('origin_order_id', sa.UUID(), nullable=True),
        sa.Column('vehicle', sa.String(length=16), nullable=False),
        sa.Column('profile', sa.String(length=16), nullable=False),
        sa.Column('capacity', sa.Integer(), nullable=False),
        sa.Column('endpoint_kind', sa.String(length=16), nullable=False),
        sa.Column('open_route', sa.Boolean(), nullable=False),
        sa.Column('road_distance_m', sa.Integer(), nullable=False),
        sa.Column('road_duration_s', sa.Integer(), nullable=False),
        sa.Column('rider_route_version', sa.Integer(), nullable=False),
        sa.Column('round_route_version', sa.Integer(), nullable=False),
        sa.Column('input_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('provenance', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('superseded_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('revision >= 1', name='ck_route_revisions_revision'),
        sa.CheckConstraint("trigger IN ('rider_request','endpoint_change')", name='ck_route_revisions_trigger'),
        sa.CheckConstraint("origin_kind IN ('current_position','last_completed_stop','configured_start')",
                           name='ck_route_revisions_origin_kind'),
        sa.CheckConstraint("(origin_kind = 'last_completed_stop') = (origin_order_id IS NOT NULL)",
                           name='ck_route_revisions_origin_order'),
        sa.CheckConstraint("vehicle IN ('scooter','bike')", name='ck_route_revisions_vehicle'),
        sa.CheckConstraint("(vehicle = 'scooter') = (profile = 'motor_scooter')", name='ck_route_revisions_vehicle_profile'),
        sa.CheckConstraint("endpoint_kind IN ('office','warehouse','home','last_stop','custom')",
                           name='ck_route_revisions_endpoint'),
        sa.CheckConstraint("open_route = (endpoint_kind = 'last_stop')", name='ck_route_revisions_open_route'),
        sa.CheckConstraint('road_distance_m >= 0 AND road_duration_s >= 0', name='ck_route_revisions_costs'),
        sa.CheckConstraint('rider_route_version >= 1 AND round_route_version >= 1', name='ck_route_revisions_versions'),
        sa.ForeignKeyConstraint(['round_id'], ['delivery_rounds.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['plan_id', 'rider_id'], ['plan_routes.plan_id', 'plan_routes.rider_id'],
                                name='fk_route_revisions_plan_route', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_id'], ['planning_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['origin_order_id'], ['orders.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('plan_id', 'rider_id', 'revision', name='uq_route_revisions_number'),
        sa.UniqueConstraint('run_id'),
    )
    op.create_index(op.f('ix_route_revisions_round_id'), 'route_revisions', ['round_id'], unique=False)
    op.create_index('uq_route_revisions_one_current', 'route_revisions', ['plan_id', 'rider_id'], unique=True,
                    postgresql_where=sa.text('is_current'))
    op.create_table(
        'revision_orders',
        sa.Column('revision_id', sa.UUID(), nullable=False),
        sa.Column('order_id', sa.UUID(), nullable=False),
        sa.Column('stop_seq', sa.Integer(), nullable=False),
        sa.CheckConstraint('stop_seq >= 1', name='ck_revision_orders_seq'),
        sa.ForeignKeyConstraint(['revision_id'], ['route_revisions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('revision_id', 'order_id'),
    )
    op.create_index('ix_revision_orders_seq', 'revision_orders', ['revision_id', 'stop_seq'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_revision_orders_seq', table_name='revision_orders')
    op.drop_table('revision_orders')
    op.drop_index('uq_route_revisions_one_current', table_name='route_revisions', postgresql_where=sa.text('is_current'))
    op.drop_index(op.f('ix_route_revisions_round_id'), table_name='route_revisions')
    op.drop_table('route_revisions')
    # Rider runs have no meaning without 4B; drop them so the single active-run index can return.
    op.execute("DELETE FROM planning_runs WHERE scope = 'rider'")
    op.drop_index('uq_planning_runs_one_active_rider', table_name='planning_runs',
                  postgresql_where=sa.text(f"{ACTIVE} AND scope = 'rider'"))
    op.drop_index('uq_planning_runs_one_active_round', table_name='planning_runs',
                  postgresql_where=sa.text(f"{ACTIVE} AND scope = 'round'"))
    op.create_index('uq_planning_runs_one_active', 'planning_runs', ['round_id'], unique=True,
                    postgresql_where=sa.text(ACTIVE))
    for ck in ('ck_planning_runs_origin_kind', 'ck_planning_runs_rider_fields', 'ck_planning_runs_rider_scope',
               'ck_planning_runs_scope'):
        op.drop_constraint(ck, 'planning_runs', type_='check')
    op.drop_constraint('fk_planning_runs_base_plan_id', 'planning_runs', type_='foreignkey')
    op.drop_constraint('fk_planning_runs_rider_id', 'planning_runs', type_='foreignkey')
    for col in ('origin_kind', 'base_plan_id', 'rider_id', 'scope'):
        op.drop_column('planning_runs', col)
    op.drop_constraint('ck_orders_completed_only_when_completed', 'orders', type_='check')
    op.drop_constraint('ck_orders_completed_pair', 'orders', type_='check')
    op.drop_constraint('fk_orders_completed_by', 'orders', type_='foreignkey')
    op.drop_column('orders', 'completed_by')
    op.drop_column('orders', 'completed_at')
    op.drop_column('plan_routes', 'rider_route_version')
    op.drop_constraint('ck_round_riders_route_version', 'round_riders', type_='check')
    op.drop_column('round_riders', 'route_version')
