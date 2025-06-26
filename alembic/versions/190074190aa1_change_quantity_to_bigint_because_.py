"""change_quantity_to_bigint_because_someone_needs_billions_of_gods

Revision ID: 190074190aa1
Revises: b957a8114a11
Create Date: 2025-06-25 21:53:34.332866

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '190074190aa1'
down_revision: Union[str, Sequence[str], None] = 'b957a8114a11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Someone wants 10 billion shadow gods. Who am I to judge?
    op.alter_column('esprit', 'quantity',
        existing_type=sa.INTEGER(),
        type_=sa.BIGINT(),
        nullable=False,
        existing_nullable=False
    )

def downgrade():
    # Good luck fitting 10 billion back into int32
    # This will explode if you actually have >2.1B of anything
    op.alter_column('esprit', 'quantity',
        existing_type=sa.BIGINT(),
        type_=sa.INTEGER(),
        nullable=False,
        existing_nullable=False
    )
