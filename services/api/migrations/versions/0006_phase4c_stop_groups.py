"""phase 4C: same-building stop groups

No new table. `orders.building_id` (present since the initial schema, never set) becomes the
admin-confirmed stop-group id:
- a length check (the id is server-generated and opaque);
- a group member must have a resolved pin (a pin that stops being resolved leaves its group first);
- a partial index on (round_id, building_id) for group lookups.

"Identical stored pins, one round, at least two members" cannot be written as a CHECK; the API
enforces it under lock and the planner re-checks location equality when it groups. Existing rows
all have a NULL building_id, so nothing is grouped by this migration.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-20
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint('ck_orders_building_id_length', 'orders',
                               'building_id IS NULL OR length(building_id) BETWEEN 8 AND 64')
    op.create_check_constraint('ck_orders_building_resolved', 'orders',
                               "building_id IS NULL OR location_state = 'resolved'")
    op.create_index('ix_orders_round_building', 'orders', ['round_id', 'building_id'], unique=False,
                    postgresql_where=sa.text('building_id IS NOT NULL'))


def downgrade() -> None:
    op.drop_index('ix_orders_round_building', table_name='orders', postgresql_where=sa.text('building_id IS NOT NULL'))
    op.drop_constraint('ck_orders_building_resolved', 'orders', type_='check')
    op.drop_constraint('ck_orders_building_id_length', 'orders', type_='check')
