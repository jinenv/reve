import asyncio
import sys
import os

# Add the parent directory to the path so we can import src
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from src.utils.database_service import DatabaseService
from src.database.models import EspritBase
async def check_tier1_esprits():
    async with DatabaseService.get_transaction() as session:
        # Get ALL tier 1 esprits
        stmt = select(EspritBase).where(EspritBase.base_tier == 1)  # type: ignore
        result = await session.execute(stmt)
        tier1_esprits = result.scalars().all()
        
        print(f"\n=== TIER 1 ESPRITS IN DATABASE ===")
        print(f"Total found: {len(tier1_esprits)}")
        print("\nList of Tier 1 Esprits:")
        for esprit in tier1_esprits:
            print(f"  - {esprit.name} ({esprit.element})")
        
        # Check if our starter names exist
        starter_names = ['Blazeblob', 'Muddroot', 'Droozle', 'Jelune', 'Gloomb', 'Shynix']
        print(f"\n=== CHECKING STARTER NAMES ===")
        for name in starter_names:
            stmt = select(EspritBase).where(EspritBase.name == name) # type: ignore
            result = await session.execute(stmt)
            exists = result.scalar_one_or_none()
            if exists:
                print(f"✅ {name} - FOUND (Tier {exists.base_tier})")
            else:
                print(f"❌ {name} - NOT FOUND")

# If running as a command in your bot, use this instead:
# await check_tier1_esprits()

# If running as a standalone script:
if __name__ == "__main__":
    asyncio.run(check_tier1_esprits())