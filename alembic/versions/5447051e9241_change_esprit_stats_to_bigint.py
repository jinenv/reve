"""change_esprit_stats_to_bigint

Revision ID: 5447051e9241
Revises: cdfc6407423d
Create Date: 2025-06-24 19:18:11.211552

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5447051e9241'
down_revision: Union[str, Sequence[str], None] = 'cdfc6407423d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Change INTEGER columns to BIGINT
    op.alter_column('esprit_base', 'base_atk',
                    existing_type=sa.INTEGER(),
                    type_=sa.BigInteger(),
                    existing_nullable=False)
    
    op.alter_column('esprit_base', 'base_def',
                    existing_type=sa.INTEGER(),
                    type_=sa.BigInteger(),
                    existing_nullable=False)
    
    op.alter_column('esprit_base', 'base_hp',
                    existing_type=sa.INTEGER(),
                    type_=sa.BigInteger(),
                    existing_nullable=False)


def downgrade() -> None:
    # Change back to INTEGER (might fail if values too large!)
    op.alter_column('esprit_base', 'base_hp',
                    existing_type=sa.BigInteger(),
                    type_=sa.INTEGER(),
                    existing_nullable=False)
    
    op.alter_column('esprit_base', 'base_def',
                    existing_type=sa.BigInteger(),
                    type_=sa.INTEGER(),
                    existing_nullable=False)
    
    op.alter_column('esprit_base', 'base_atk',
                    existing_type=sa.BigInteger(),
                    type_=sa.INTEGER(),
                    existing_nullable=False)
