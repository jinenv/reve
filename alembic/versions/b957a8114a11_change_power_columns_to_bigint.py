"""change_power_columns_to_bigint

Revision ID: b957a8114a11
Revises: 5447051e9241
Create Date: 2025-06-25 21:43:44.927270

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b957a8114a11'
down_revision: Union[str, Sequence[str], None] = '5447051e9241'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Change INT columns to BIGINT because someone gave themselves
    # 10000 tier 18 esprits and broke PostgreSQL
    op.alter_column('player', 'total_attack_power',
        existing_type=sa.INTEGER(),
        type_=sa.BIGINT(),
        nullable=False
    )
    op.alter_column('player', 'total_defense_power',
        existing_type=sa.INTEGER(),
        type_=sa.BIGINT(),
        nullable=False
    )
    op.alter_column('player', 'total_hp',
        existing_type=sa.INTEGER(),
        type_=sa.BIGINT(),
        nullable=False
    )

def downgrade():
    # Good luck fitting 266 billion back into INT32 lmao
    op.alter_column('player', 'total_hp',
        existing_type=sa.BIGINT(),
        type_=sa.INTEGER(),
        nullable=False
    )
    op.alter_column('player', 'total_defense_power',
        existing_type=sa.BIGINT(),
        type_=sa.INTEGER(),
        nullable=False
    )
    op.alter_column('player', 'total_attack_power',
        existing_type=sa.BIGINT(),
        type_=sa.INTEGER(),
        nullable=False
    )