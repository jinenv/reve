"""jiji_final_system

Revision ID: jiji_system_001
Revises: ce5812af6c52
Create Date: 2025-06-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'jiji_system_001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema for Jiji Monster Warlord style systems."""
    
    # Add type field to esprit_base
    with op.batch_alter_table('esprit_base', schema=None) as batch_op:
        batch_op.add_column(sa.Column('type', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='warrior'))
        batch_op.add_column(sa.Column('base_atk', sa.Integer(), nullable=False, server_default='15'))
        batch_op.add_column(sa.Column('base_def', sa.Integer(), nullable=False, server_default='10'))
        batch_op.add_column(sa.Column('base_hp', sa.Integer(), nullable=False, server_default='100'))
        batch_op.add_column(sa.Column('image_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('abilities', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()))
        batch_op.create_index(batch_op.f('ix_esprit_base_type'), ['type'], unique=False)
        # Drop old portrait/full_body columns
        batch_op.drop_column('portrait_url')
        batch_op.drop_column('full_body_url')
        # Drop slug as we use name
        batch_op.drop_index('ix_esprit_base_slug')
        batch_op.drop_column('slug')
        # Make name unique
        batch_op.create_index(batch_op.f('ix_esprit_base_name'), ['name'], unique=True)
    
    # Update player table for leader system and space mechanics
    with op.batch_alter_table('player', schema=None) as batch_op:
        # Leader system
        batch_op.add_column(sa.Column('leader_esprit_stack_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_player_leader_esprit', 'esprit', ['leader_esprit_stack_id'], ['id'])
        
        # Space system
        batch_op.add_column(sa.Column('max_space', sa.Integer(), nullable=False, server_default='50'))
        batch_op.add_column(sa.Column('current_space', sa.Integer(), nullable=False, server_default='0'))
        
        # Combat power cache
        batch_op.add_column(sa.Column('total_attack_power', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('total_defense_power', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('total_hp', sa.Integer(), nullable=False, server_default='0'))
        
        # Tier-based fragment system (not element-based)
        batch_op.add_column(sa.Column('tier_fragments', postgresql.JSON(astext_type=sa.Text()), nullable=True))
        
        # Remove team-related columns (no more teams, just leader)
        batch_op.drop_column('active_team')
        batch_op.drop_column('team_slots')
        batch_op.drop_column('max_team_cost')
        
        # Remove old summon tracking
        batch_op.drop_column('total_summons')
        batch_op.drop_column('legendary_summons')
        batch_op.drop_column('last_summon')
        
        # Add fusion tracking
        batch_op.add_column(sa.Column('total_fusions', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('successful_fusions', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('total_awakenings', sa.Integer(), nullable=False, server_default='0'))
    
    # Update esprit table
    with op.batch_alter_table('esprit', schema=None) as batch_op:
        # Space values
        batch_op.add_column(sa.Column('space_per_unit', sa.Integer(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('total_space', sa.Integer(), nullable=False, server_default='1'))
        
        # Remove old awakening columns
        batch_op.drop_column('awakening_slots')
        batch_op.drop_column('awakening_bonuses')
        
        # Ensure awakening_level has proper constraint (0-5)
        batch_op.alter_column('awakening_level',
                              existing_type=sa.Integer(),
                              type_=sa.Integer(),
                              existing_nullable=False,
                              nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Restore team system
    with op.batch_alter_table('player', schema=None) as batch_op:
        batch_op.add_column(sa.Column('active_team', postgresql.JSON(astext_type=sa.Text()), nullable=True))
        batch_op.add_column(sa.Column('team_slots', sa.Integer(), nullable=False, server_default='5'))
        batch_op.add_column(sa.Column('max_team_cost', sa.Integer(), nullable=False, server_default='100'))
        
        # Restore summon tracking
        batch_op.add_column(sa.Column('total_summons', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('legendary_summons', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('last_summon', sa.DateTime(), nullable=True))
        
        # Remove Jiji systems
        batch_op.drop_constraint('fk_player_leader_esprit', type_='foreignkey')
        batch_op.drop_column('leader_esprit_stack_id')
        batch_op.drop_column('max_space')
        batch_op.drop_column('current_space')
        batch_op.drop_column('total_attack_power')
        batch_op.drop_column('total_defense_power')
        batch_op.drop_column('total_hp')
        batch_op.drop_column('tier_fragments')
        batch_op.drop_column('total_fusions')
        batch_op.drop_column('successful_fusions')
        batch_op.drop_column('total_awakenings')
    
    with op.batch_alter_table('esprit', schema=None) as batch_op:
        batch_op.drop_column('space_per_unit')
        batch_op.drop_column('total_space')
        batch_op.add_column(sa.Column('awakening_slots', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('awakening_bonuses', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    
    with op.batch_alter_table('esprit_base', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_esprit_base_type'))
        batch_op.drop_index(batch_op.f('ix_esprit_base_name'))
        batch_op.drop_column('type')
        batch_op.drop_column('base_atk')
        batch_op.drop_column('base_def')
        batch_op.drop_column('base_hp')
        batch_op.drop_column('image_url')
        batch_op.drop_column('abilities')
        batch_op.drop_column('created_at')
        batch_op.add_column(sa.Column('slug', sqlmodel.sql.sqltypes.AutoString(), nullable=False))
        batch_op.add_column(sa.Column('portrait_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('full_body_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.create_index(batch_op.f('ix_esprit_base_slug'), ['slug'], unique=True)