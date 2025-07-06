"""add reve cooldown to players

Revision ID: 092a83c1ced5
Revises: a71e1363aee8
Create Date: 2025-07-06 17:41:09.525144

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '092a83c1ced5'
down_revision: Union[str, Sequence[str], None] = 'a71e1363aee8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add reve_cooldown_expires column
    op.add_column('player', sa.Column('reve_cooldown_expires', sa.DateTime(), nullable=True))


def downgrade() -> None:
    # Remove reve_cooldown_expires column
    op.drop_column('player', 'reve_cooldown_expires')
