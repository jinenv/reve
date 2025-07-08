"""Add reve charges system

Revision ID: a59998b48ad5
Revises: 5da98eb7ba6c
Create Date: 2025-07-08 16:56:04.375566

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a59998b48ad5'
down_revision: Union[str, Sequence[str], None] = '5da98eb7ba6c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add reve charges system fields and remove old cooldown field"""
    # Add new reve charges fields
    op.add_column('player', sa.Column('reve_charges', sa.Integer(), nullable=False, server_default='5'))
    op.add_column('player', sa.Column('last_reve_charge_time', sa.DateTime(), nullable=True))
    
    # Remove server_default after adding the column (best practice)
    op.alter_column('player', 'reve_charges', server_default=None)
    
    # Drop the old reve cooldown field (clean break)
    op.drop_column('player', 'reve_cooldown_expires')


def downgrade() -> None:
    """Revert to old reve cooldown system"""
    # Add back the old cooldown field
    op.add_column('player', sa.Column('reve_cooldown_expires', sa.DateTime(), nullable=True))
    
    # Remove the new charges fields
    op.drop_column('player', 'last_reve_charge_time')
    op.drop_column('player', 'reve_charges')
