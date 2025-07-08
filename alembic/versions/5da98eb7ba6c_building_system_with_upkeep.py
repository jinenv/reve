"""building_system_with_upkeep

Revision ID: 5da98eb7ba6c
Revises: 79b5cf31f729
Create Date: 2025-07-08 04:21:14.299018

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5da98eb7ba6c'
down_revision: Union[str, Sequence[str], None] = '79b5cf31f729'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    # Add new building count and level fields
    op.add_column('player', sa.Column('shrine_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('player', sa.Column('shrine_level', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('player', sa.Column('cluster_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('player', sa.Column('cluster_level', sa.Integer(), nullable=False, server_default='1'))
    
    # Add separate pending income fields for each currency
    op.add_column('player', sa.Column('pending_revies_income', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('player', sa.Column('pending_erythl_income', sa.Integer(), nullable=False, server_default='0'))
    
    # Transfer existing pending_building_income to pending_revies_income (assume all was revies)
    connection = op.get_bind()
    connection.execute(sa.text("""
        UPDATE player 
        SET pending_revies_income = COALESCE(pending_building_income, 0)
        WHERE pending_building_income IS NOT NULL AND pending_building_income > 0
    """))
    
    # Update building_slots default from 3 to 2
    op.alter_column('player', 'building_slots', server_default='2')
    
    # Remove the old single pending_building_income field
    op.drop_column('player', 'pending_building_income')
    
    # Remove the old total_buildings_owned field (now calculated from shrine_count + cluster_count)
    op.drop_column('player', 'total_buildings_owned')
    
    # Remove server defaults to keep schema clean
    op.alter_column('player', 'building_slots', server_default=None)
    op.alter_column('player', 'shrine_count', server_default=None)
    op.alter_column('player', 'shrine_level', server_default=None)
    op.alter_column('player', 'cluster_count', server_default=None)
    op.alter_column('player', 'cluster_level', server_default=None)
    op.alter_column('player', 'pending_revies_income', server_default=None)
    op.alter_column('player', 'pending_erythl_income', server_default=None)

def downgrade() -> None:
    """Downgrade schema."""
    
    # Add back the old fields
    op.add_column('player', sa.Column('pending_building_income', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('player', sa.Column('total_buildings_owned', sa.Integer(), nullable=False, server_default='0'))
    
    # Transfer pending income back (combine both currencies)
    connection = op.get_bind()
    connection.execute(sa.text("""
        UPDATE player 
        SET pending_building_income = COALESCE(pending_revies_income, 0) + COALESCE(pending_erythl_income, 0),
            total_buildings_owned = COALESCE(shrine_count, 0) + COALESCE(cluster_count, 0)
    """))
    
    # Remove new building fields
    op.drop_column('player', 'pending_erythl_income')
    op.drop_column('player', 'pending_revies_income')
    op.drop_column('player', 'cluster_level')
    op.drop_column('player', 'cluster_count')
    op.drop_column('player', 'shrine_level')
    op.drop_column('player', 'shrine_count')
    
    # Revert building_slots default to 3
    op.alter_column('player', 'building_slots', server_default='3')