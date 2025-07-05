"""add_player_classes

Revision ID: a4171a3f77af
Revises: ee9efca6d76e
Create Date: 2025-07-04 20:41:35.755060

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4171a3f77af'
down_revision: Union[str, Sequence[str], None] = 'ee9efca6d76e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create player_class table
    op.create_table(
        'player_class',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('class_type', sa.String(), nullable=False),
        sa.Column('selected_at', sa.DateTime(), nullable=False),
        sa.Column('class_change_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_cost_paid', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_bonus_revies_earned', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_bonus_applications', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('bonus_tracking', sa.JSON(), nullable=True),
        sa.Column('energy_bonus_minutes_saved', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('stamina_bonus_minutes_saved', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['player_id'], ['player.id'], ),
        sa.UniqueConstraint('player_id')
    )
    
    # Create indexes
    op.create_index('ix_player_class_player_id', 'player_class', ['player_id'])
    op.create_index('ix_player_class_class_type', 'player_class', ['class_type'])
    op.create_index('ix_player_class_selected_at', 'player_class', ['selected_at'])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes
    op.drop_index('ix_player_class_selected_at', table_name='player_class')
    op.drop_index('ix_player_class_class_type', table_name='player_class')
    op.drop_index('ix_player_class_player_id', table_name='player_class')
    
    # Drop table
    op.drop_table('player_class')
