"""add power_last_calculated to player

Revision ID: 3f54be191a0a
Revises: b526068739f3
Create Date: 2025-06-30 20:06:38.580154

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f54be191a0a'
down_revision: Union[str, Sequence[str], None] = 'b526068739f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add power_last_calculated column to player table."""
    op.add_column('player', sa.Column('power_last_calculated', sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE player SET power_last_calculated = NOW() WHERE power_last_calculated IS NULL")

def downgrade() -> None:
    """Remove power_last_calculated column from player table."""
    op.drop_column('player', 'power_last_calculated')