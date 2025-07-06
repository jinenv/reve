"""Add username default value manually

Revision ID: a71e1363aee8
Revises: 0a9f7f572a01
Create Date: 2025-07-05 21:24:17.239943

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a71e1363aee8'
down_revision: Union[str, Sequence[str], None] = '0a9f7f572a01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE player ALTER COLUMN username SET DEFAULT 'Unknown Player';")

def downgrade() -> None:
    op.execute("ALTER TABLE player ALTER COLUMN username DROP DEFAULT;")
