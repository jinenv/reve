"""Add universal relic slots to EspritBase

Revision ID: b526068739f3
Revises: 190074190aa1
Create Date: 2025-06-29 05:00:35.906945

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b526068739f3'
down_revision: Union[str, Sequence[str], None] = '190074190aa1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add universal relic slots column to esprit_base"""
    # Add the new column
    op.add_column('esprit_base', 
        sa.Column('equipped_relics', 
                 postgresql.JSON(astext_type=sa.Text()), 
                 nullable=True)
    )
    
    # Set default empty arrays for existing records
    op.execute("UPDATE esprit_base SET equipped_relics = '[]'::json WHERE equipped_relics IS NULL")
    
    # Make it not nullable now that we have defaults
    op.alter_column('esprit_base', 'equipped_relics', nullable=False)

def downgrade() -> None:
    """Remove relic slots if we need to rollback"""
    op.drop_column('esprit_base', 'equipped_relics')
