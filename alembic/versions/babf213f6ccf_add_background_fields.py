from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers, used by Alembic.
revision: str = 'babf213f6ccf'
down_revision: Union[str, Sequence[str], None] = 'fa5b376dc157'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add the column as nullable=True temporarily
    op.add_column('player', sa.Column('last_income_collection', sa.DateTime(), nullable=True))

    # 2. Backfill all existing rows with a default value (safe starting timestamp)
    op.execute(
        f"UPDATE player SET last_income_collection = '{datetime.utcnow().isoformat(sep=' ', timespec='seconds')}'"
    )

    # 3. Alter column to nullable=False after data is filled
    op.alter_column('player', 'last_income_collection', nullable=False)

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('player', 'last_income_collection')
