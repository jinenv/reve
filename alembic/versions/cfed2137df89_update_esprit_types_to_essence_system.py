
"""update_esprit_types_to_essence_system

Revision ID: cfed2137df89
Revises: 6d814b1ab815
Create Date: 2025-06-20 20:26:03.573171

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cfed2137df89'
down_revision: Union[str, Sequence[str], None] = '6d814b1ab815'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Update esprit types from old RPG system to essence-based system"""
    
    # First, update any existing data
    op.execute("UPDATE esprit_base SET type = 'chaos' WHERE type = 'warrior'")
    op.execute("UPDATE esprit_base SET type = 'order' WHERE type = 'guardian'")
    op.execute("UPDATE esprit_base SET type = 'hunt' WHERE type = 'scout'")
    op.execute("UPDATE esprit_base SET type = 'wisdom' WHERE type = 'mystic'")
    op.execute("UPDATE esprit_base SET type = 'command' WHERE type = 'titan'")
    
    # Update the column default at database level
    op.alter_column('esprit_base', 'type',
                    existing_type=sa.String(),
                    server_default='chaos',
                    nullable=False)


def downgrade() -> None:
    """Revert esprit types back to old RPG system"""
    
    # Revert the data updates
    op.execute("UPDATE esprit_base SET type = 'warrior' WHERE type = 'chaos'")
    op.execute("UPDATE esprit_base SET type = 'guardian' WHERE type = 'order'")
    op.execute("UPDATE esprit_base SET type = 'scout' WHERE type = 'hunt'")
    op.execute("UPDATE esprit_base SET type = 'mystic' WHERE type = 'wisdom'")
    op.execute("UPDATE esprit_base SET type = 'titan' WHERE type = 'command'")
    
    # Revert the column default
    op.alter_column('esprit_base', 'type',
                    existing_type=sa.String(),
                    server_default='warrior',
                    nullable=False)