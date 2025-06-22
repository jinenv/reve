"""Add tier_name column and update abilities type

Revision ID: b0a46dea8fa4
Revises: cfed2137df89
Create Date: 2025-06-21 [timestamp]

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b0a46dea8fa4'
down_revision: Union[str, Sequence[str], None] = 'cfed2137df89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add tier_name column and ensure abilities is JSON type"""
    
    # First, check if tier_name column already exists
    conn = op.get_bind()
    result = conn.execute(sa.text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='esprit_base' AND column_name='tier_name'
    """))
    tier_name_exists = result.fetchone() is not None
    
    # Add tier_name column if it doesn't exist
    if not tier_name_exists:
        op.add_column('esprit_base', sa.Column('tier_name', sa.String(), nullable=True))
    
    # Check current type of abilities column
    result = conn.execute(sa.text("""
        SELECT data_type 
        FROM information_schema.columns 
        WHERE table_name='esprit_base' AND column_name='abilities'
    """))
    current_type = result.fetchone()
    
    # Only alter if it's not already json or jsonb
    if current_type and current_type[0] not in ('json', 'jsonb'):
        # Handle different possible current types
        if current_type[0] == 'text':
            op.execute('ALTER TABLE esprit_base ALTER COLUMN abilities TYPE JSON USING abilities::json')
        elif current_type[0] == 'character varying':
            op.execute('ALTER TABLE esprit_base ALTER COLUMN abilities TYPE JSON USING abilities::json')
        else:
            # For any other type, try to convert via text
            op.execute('ALTER TABLE esprit_base ALTER COLUMN abilities TYPE JSON USING abilities::text::json')
    
    # Update tier names based on base_tier
    op.execute("""
        UPDATE esprit_base SET tier_name = CASE
            WHEN base_tier = 1 THEN 'Common'
            WHEN base_tier = 2 THEN 'Uncommon'
            WHEN base_tier = 3 THEN 'Rare'
            WHEN base_tier = 4 THEN 'Epic'
            WHEN base_tier = 5 THEN 'Mythic'
            WHEN base_tier = 6 THEN 'Celestial'
            WHEN base_tier = 7 THEN 'Divine'
            WHEN base_tier = 8 THEN 'Primal'
            WHEN base_tier = 9 THEN 'Sovereign'
            WHEN base_tier = 10 THEN 'Astral'
            WHEN base_tier = 11 THEN 'Ethereal'
            WHEN base_tier = 12 THEN 'Transcendent'
            WHEN base_tier = 13 THEN 'Empyrean'
            WHEN base_tier = 14 THEN 'Absolute'
            WHEN base_tier = 15 THEN 'Genesis'
            WHEN base_tier = 16 THEN 'Legendary'
            WHEN base_tier = 17 THEN 'Void'
            WHEN base_tier = 18 THEN 'Singularity'
            ELSE 'Unknown'
        END
        WHERE tier_name IS NULL OR tier_name = ''
    """)
    
    # Create index on tier_name for faster queries
    op.create_index(op.f('ix_esprit_base_tier_name'), 'esprit_base', ['tier_name'], unique=False)


def downgrade() -> None:
    """Remove tier_name column and revert abilities type"""
    
    # Drop index first
    op.drop_index(op.f('ix_esprit_base_tier_name'), table_name='esprit_base')
    
    # Drop tier_name column
    op.drop_column('esprit_base', 'tier_name')
    
    # Note: We don't revert the abilities column type as JSON is likely the desired type
