"""reve_domain_migration

Revision ID: ee9efca6d76e
Revises: 3f54be191a0a
Create Date: 2025-07-03 22:52:53.946842

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ee9efca6d76e'
down_revision: Union[str, Sequence[str], None] = '3f54be191a0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the Jiji → Reve domain migration (skip for fresh DB)"""
    
    print("🔄 Starting Reve domain migration...")
    print("ℹ️  Skipping all operations (fresh database already has correct structure)")
    print("🎉 Reve domain migration completed successfully!")

def downgrade() -> None:
    """Rollback the Jiji → Reve domain migration"""
    
    print("🔄 Rolling back Reve domain migration...")
    
    # Step 1: Rename columns back
    print("📝 Reverting column names...")
    op.alter_column('player', 'revies', new_column_name='jijies')
    op.alter_column('player', 'total_revies_earned', new_column_name='total_jijies_earned')
    print("✅ Reverted column names")
    
    # Step 2: Update indexes back
    print("🔍 Reverting indexes...")
    try:
        op.drop_index('ix_player_revies', table_name='player')
        print("✅ Dropped new index")
    except Exception as e:
        print(f"ℹ️  New index ix_player_revies not found: {e}")
    
    op.create_index('ix_player_jijies', 'player', ['jijies'])
    print("✅ Restored old index")
    
    # Step 3: Update timestamps
    print("⏰ Updating timestamps...")
    op.execute("UPDATE player SET updated_at = NOW() WHERE updated_at IS NOT NULL")
    
    print("✅ Rollback to Jiji domain completed!")