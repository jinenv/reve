# reset_migrations.py
"""
Complete Alembic migration reset script
WARNING: This will DROP ALL TABLES and reset migrations from scratch
"""

import os
import shutil
import asyncio
import asyncpg
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime

async def drop_all_tables():
    """Drop all tables including alembic_version"""
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    
    if not db_url:
        print("❌ DATABASE_URL not found")
        return False
    
    # Convert to sync URL for asyncpg
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    
    print("\n⚠️  WARNING: This will DROP ALL TABLES in the database!")
    confirm = input("Type 'YES I WANT TO DESTROY EVERYTHING' to confirm: ")
    
    if confirm != "YES I WANT TO DESTROY EVERYTHING":
        print("❌ Aborted. No changes made.")
        return False
    
    try:
        conn = await asyncpg.connect(db_url)
        
        # Get all table names
        tables = await conn.fetch("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public'
        """)
        
        if not tables:
            print("ℹ️  No tables found in database")
        else:
            print(f"\n🗑️  Dropping {len(tables)} tables...")
            
            # Drop all tables
            for table in tables:
                table_name = table['tablename']
                print(f"   Dropping {table_name}...")
                await conn.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE')
        
        # Drop all custom types (enums, etc)
        types = await conn.fetch("""
            SELECT typname FROM pg_type 
            WHERE typnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
            AND typtype = 'e'
        """)
        
        for type_rec in types:
            type_name = type_rec['typname']
            print(f"   Dropping type {type_name}...")
            await conn.execute(f'DROP TYPE IF EXISTS "{type_name}" CASCADE')
        
        await conn.close()
        print("✅ All tables and types dropped successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error dropping tables: {e}")
        return False

def clean_alembic_versions():
    """Remove all existing migration files"""
    versions_dir = Path("alembic/versions")
    
    if not versions_dir.exists():
        print("ℹ️  No versions directory found")
        return
    
    # Backup first
    backup_dir = Path(f"alembic_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    print(f"\n📦 Creating backup at {backup_dir}")
    shutil.copytree("alembic", backup_dir)
    
    # Remove all migration files
    migration_files = list(versions_dir.glob("*.py"))
    
    if not migration_files:
        print("ℹ️  No migration files found")
    else:
        print(f"\n🗑️  Removing {len(migration_files)} migration files...")
        for file in migration_files:
            print(f"   Removing {file.name}")
            file.unlink()
    
    print("✅ Migration files cleaned")

async def verify_clean_state():
    """Verify database is in clean state"""
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    
    if not db_url:
        return False
    
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    
    try:
        conn = await asyncpg.connect(db_url)
        
        # Check for any remaining tables
        table_count = await conn.fetchval("""
            SELECT COUNT(*) FROM pg_tables 
            WHERE schemaname = 'public'
        """)
        
        await conn.close()
        
        if table_count == 0:
            print("\n✅ Database is clean - no tables exist")
            return True
        else:
            print(f"\n⚠️  Warning: {table_count} tables still exist in database")
            return False
            
    except Exception as e:
        print(f"❌ Error verifying database state: {e}")
        return False

async def main():
    print("🐱 Jiji Migration Reset Tool")
    print("=" * 50)
    print("This will:")
    print("  1. Drop ALL tables from the database")
    print("  2. Remove all Alembic migration files")
    print("  3. Leave you with a clean slate")
    print("=" * 50)
    
    # Step 1: Drop all tables
    if not await drop_all_tables():
        print("\n❌ Failed to drop tables. Aborting.")
        return
    
    # Step 2: Clean migration files
    clean_alembic_versions()
    
    # Step 3: Verify
    await verify_clean_state()
    
    print("\n" + "=" * 50)
    print("✅ Migration reset complete!")
    print("\nNext steps:")
    print("  1. Create new initial migration:")
    print("     alembic revision --autogenerate -m \"initial migration\"")
    print("  2. Apply the migration:")
    print("     alembic upgrade head")
    print("  3. Seed your database if needed:")
    print("     python scripts/seed_database.py")

if __name__ == "__main__":
    asyncio.run(main())
