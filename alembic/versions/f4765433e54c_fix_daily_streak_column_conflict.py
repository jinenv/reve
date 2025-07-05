"""fix_daily_streak_column_conflict

Revision ID: [auto_generated]
Revises: a4171a3f77af
Create Date: [auto_generated]
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '[auto_generated]'
down_revision: Union[str, Sequence[str], None] = 'a4171a3f77af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Fix daily_streak column conflict"""
    
    # Check if both columns exist
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = [col['name'] for col in inspector.get_columns('player')]
    
    has_daily_streak = 'daily_streak' in columns
    has_daily_quest_streak = 'daily_quest_streak' in columns
    
    print(f"🔍 Column check: daily_streak={has_daily_streak}, daily_quest_streak={has_daily_quest_streak}")
    
    if has_daily_streak and has_daily_quest_streak:
        # Both exist - merge data and drop old column
        print("📊 Merging daily_streak data into daily_quest_streak...")
        
        # Merge data: use daily_quest_streak if > 0, otherwise use daily_streak
        op.execute("""
            UPDATE player 
            SET daily_quest_streak = GREATEST(daily_quest_streak, daily_streak)
            WHERE daily_streak > daily_quest_streak
        """)
        
        # Drop the old column
        print("🗑️ Dropping redundant daily_streak column...")
        op.drop_column('player', 'daily_streak')
        
    elif has_daily_streak and not has_daily_quest_streak:
        # Only old column exists - rename it
        print("🔄 Renaming daily_streak to daily_quest_streak...")
        op.alter_column('player', 'daily_streak', new_column_name='daily_quest_streak')
        
    elif not has_daily_streak and has_daily_quest_streak:
        # Only new column exists - nothing to do
        print("✅ daily_quest_streak already exists and daily_streak is gone")
        
    else:
        # Neither exists - create the new one
        print("➕ Creating daily_quest_streak column...")
        op.add_column('player', sa.Column('daily_quest_streak', sa.Integer(), nullable=False, server_default='0'))

def downgrade() -> None:
    """Revert daily_streak column fix"""
    # For safety, recreate daily_streak with current daily_quest_streak values
    op.add_column('player', sa.Column('daily_streak', sa.Integer(), nullable=False, server_default='0'))
    op.execute("UPDATE player SET daily_streak = daily_quest_streak")