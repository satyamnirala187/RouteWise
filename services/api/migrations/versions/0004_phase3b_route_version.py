"""phase 3B: route_version separates saved-route usability from planning-input revisions

`delivery_rounds.route_version` increases with every planning-input change except a rider's own
delivery progress; `route_plans.route_version` records it when a plan is committed. Existing
rows copy their `input_version`, so every existing plan keeps exactly the out-of-date state it
had before this migration (it was input_version != round.input_version).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('delivery_rounds', sa.Column('route_version', sa.Integer(), server_default=sa.text('1'), nullable=False))
    op.execute("UPDATE delivery_rounds SET route_version = input_version")
    op.create_check_constraint('ck_rounds_route_version', 'delivery_rounds', 'route_version >= 1')
    op.add_column('route_plans', sa.Column('route_version', sa.Integer(), nullable=True))
    op.execute("UPDATE route_plans SET route_version = input_version")
    op.alter_column('route_plans', 'route_version', nullable=False)
    op.create_check_constraint('ck_route_plans_route_version', 'route_plans', 'route_version >= 1')


def downgrade() -> None:
    op.drop_constraint('ck_route_plans_route_version', 'route_plans', type_='check')
    op.drop_column('route_plans', 'route_version')
    op.drop_constraint('ck_rounds_route_version', 'delivery_rounds', type_='check')
    op.drop_column('delivery_rounds', 'route_version')
