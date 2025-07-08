"""add team support slots

Revision ID: fa5b376dc157
Revises: 092a83c1ced5
Create Date: 2025-07-07 19:46:45.348429

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fa5b376dc157'
down_revision: Union[str, Sequence[str], None] = '092a83c1ced5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add support team member slots to player table."""
    
    # Add support team slots
    op.add_column('player', sa.Column('support1_esprit_stack_id', sa.Integer(), nullable=True))
    op.add_column('player', sa.Column('support2_esprit_stack_id', sa.Integer(), nullable=True))
    
    # Add foreign key constraints
    op.create_foreign_key(
        'fk_player_support1_esprit_stack_id',
        'player', 'esprit',
        ['support1_esprit_stack_id'], ['id']
    )
    
    op.create_foreign_key(
        'fk_player_support2_esprit_stack_id', 
        'player', 'esprit',
        ['support2_esprit_stack_id'], ['id']
    )

def downgrade() -> None:
    """Remove support team member slots."""
    
    # Drop foreign key constraints
    op.drop_constraint('fk_player_support2_esprit_stack_id', 'player', type_='foreignkey')
    op.drop_constraint('fk_player_support1_esprit_stack_id', 'player', type_='foreignkey')
    
    # Drop columns
    op.drop_column('player', 'support2_esprit_stack_id')
    op.drop_column('player', 'support1_esprit_stack_id')
