# scripts/verify_types.py
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import asyncio
from sqlmodel import select, func, col
from src.database.models import EspritBase
from src.utils.database_service import DatabaseService
from dotenv import load_dotenv

async def verify_types():
    """Check the current types in the database"""
    load_dotenv()
    DatabaseService.init()
    
    async with DatabaseService.get_session() as session:
        # Count by type
        stmt = select(EspritBase.type, func.count()).group_by(EspritBase.type)
        results = await session.execute(stmt)
        
        print("\nCurrent Esprit Types in Database:")
        print("-" * 30)
        type_counts = list(results)
        
        if not type_counts:
            print("No Esprits found in database yet.")
            print("\nExpected types after migration:")
            print("- chaos (was warrior)")
            print("- order (was guardian)")
            print("- hunt (was scout)")
            print("- wisdom (was mystic)")
            print("- command (was titan)")
        else:
            for type_name, count in type_counts:
                print(f"{type_name}: {count} esprits")
        
        # Check if any old types remain
        old_types = ['warrior', 'guardian', 'scout', 'mystic', 'titan']
        old_stmt = select(EspritBase).where(col(EspritBase.type).in_(old_types))
        old_results = await session.execute(old_stmt)
        old_esprits = old_results.scalars().all()
        
        if old_esprits:
            print("\n⚠️ WARNING: Found Esprits with old types!")
            for esprit in old_esprits:
                print(f"  - {esprit.name} ({esprit.type})")
        else:
            print("\n✅ Migration successful! No old types found.")

if __name__ == "__main__":
    asyncio.run(verify_types())