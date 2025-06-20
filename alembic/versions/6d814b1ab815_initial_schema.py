"""initial_schema

Revision ID: 6d814b1ab815
Revises: 
Create Date: 2025-06-20 16:36:30.760266

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6d814b1ab815'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create tables in correct order to avoid circular dependency
    
    # First create esprit_base (no dependencies)
    op.create_table('esprit_base',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('element', sa.String(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('base_tier', sa.Integer(), nullable=False),
    sa.Column('base_atk', sa.Integer(), nullable=False),
    sa.Column('base_def', sa.Integer(), nullable=False),
    sa.Column('base_hp', sa.Integer(), nullable=False),
    sa.Column('description', sa.String(), nullable=False),
    sa.Column('image_url', sa.String(), nullable=True),
    sa.Column('abilities', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_esprit_base_base_tier'), 'esprit_base', ['base_tier'], unique=False)
    op.create_index(op.f('ix_esprit_base_element'), 'esprit_base', ['element'], unique=False)
    op.create_index(op.f('ix_esprit_base_name'), 'esprit_base', ['name'], unique=True)
    op.create_index(op.f('ix_esprit_base_type'), 'esprit_base', ['type'], unique=False)
    
    # Then create player (without leader foreign key initially)
    op.create_table('player',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('discord_id', sa.BigInteger(), nullable=False),  # Changed to BigInteger
    sa.Column('username', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('level', sa.Integer(), nullable=False),
    sa.Column('experience', sa.Integer(), nullable=False),
    sa.Column('energy', sa.Integer(), nullable=False),
    sa.Column('max_energy', sa.Integer(), nullable=False),
    sa.Column('last_energy_update', sa.DateTime(), nullable=False),
    sa.Column('last_active', sa.DateTime(), nullable=False),
    sa.Column('leader_esprit_stack_id', sa.Integer(), nullable=True),
    sa.Column('max_space', sa.Integer(), nullable=False),
    sa.Column('current_space', sa.Integer(), nullable=False),
    sa.Column('total_attack_power', sa.Integer(), nullable=False),
    sa.Column('total_defense_power', sa.Integer(), nullable=False),
    sa.Column('total_hp', sa.Integer(), nullable=False),
    sa.Column('current_area_id', sa.String(), nullable=False),
    sa.Column('highest_area_unlocked', sa.String(), nullable=False),
    sa.Column('quest_progress', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.Column('total_quests_completed', sa.Integer(), nullable=False),
    sa.Column('jijies', sa.Integer(), nullable=False),
    sa.Column('erythl', sa.Integer(), nullable=False),
    sa.Column('inventory', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.Column('tier_fragments', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.Column('element_fragments', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.Column('daily_quest_streak', sa.Integer(), nullable=False),
    sa.Column('last_daily_reset', sa.Date(), nullable=False),
    sa.Column('weekly_points', sa.Integer(), nullable=False),
    sa.Column('last_weekly_reset', sa.Date(), nullable=False),
    sa.Column('last_daily_echo', sa.Date(), nullable=True),
    sa.Column('total_battles', sa.Integer(), nullable=False),
    sa.Column('battles_won', sa.Integer(), nullable=False),
    sa.Column('total_fusions', sa.Integer(), nullable=False),
    sa.Column('successful_fusions', sa.Integer(), nullable=False),
    sa.Column('total_awakenings', sa.Integer(), nullable=False),
    sa.Column('total_echoes_opened', sa.Integer(), nullable=False),
    sa.Column('collections_completed', sa.Integer(), nullable=False),
    sa.Column('favorite_element', sa.String(), nullable=True),
    sa.Column('friend_code', sa.String(), nullable=True),
    sa.Column('guild_id', sa.Integer(), nullable=True),
    sa.Column('guild_contribution_points', sa.Integer(), nullable=False),
    sa.Column('notification_settings', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.Column('last_quest', sa.DateTime(), nullable=True),
    sa.Column('last_fusion', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('friend_code')
    )
    op.create_index(op.f('ix_player_discord_id'), 'player', ['discord_id'], unique=True)
    
    # Then create esprit (depends on both)
    op.create_table('esprit',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('esprit_base_id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('tier', sa.Integer(), nullable=False),
    sa.Column('awakening_level', sa.Integer(), nullable=False),
    sa.Column('element', sa.String(), nullable=False),
    sa.Column('space_per_unit', sa.Integer(), nullable=False),
    sa.Column('total_space', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_modified', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['esprit_base_id'], ['esprit_base.id'], ),
    sa.ForeignKeyConstraint(['owner_id'], ['player.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_esprit_esprit_base_id'), 'esprit', ['esprit_base_id'], unique=False)
    op.create_index(op.f('ix_esprit_owner_id'), 'esprit', ['owner_id'], unique=False)
    
    # Finally add the foreign key constraint for leader
    op.create_foreign_key('fk_player_leader_esprit', 'player', 'esprit', ['leader_esprit_stack_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop foreign key first
    op.drop_constraint('fk_player_leader_esprit', 'player', type_='foreignkey')
    
    # Then drop tables in reverse order
    op.drop_index(op.f('ix_esprit_owner_id'), table_name='esprit')
    op.drop_index(op.f('ix_esprit_esprit_base_id'), table_name='esprit')
    op.drop_table('esprit')
    
    op.drop_index(op.f('ix_player_discord_id'), table_name='player')
    op.drop_table('player')
    
    op.drop_index(op.f('ix_esprit_base_type'), table_name='esprit_base')
    op.drop_index(op.f('ix_esprit_base_name'), table_name='esprit_base')
    op.drop_index(op.f('ix_esprit_base_element'), table_name='esprit_base')
    op.drop_index(op.f('ix_esprit_base_base_tier'), table_name='esprit_base')
    op.drop_table('esprit_base')