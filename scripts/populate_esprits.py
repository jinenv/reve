"""
Enhanced script to populate/UPDATE the EspritBase table from JSON file.
This will update existing Esprits with new stats instead of just skipping them.
"""

import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import select
from src.database.models import EspritBase
from src.utils.database_service import DatabaseService
from src.utils.logger import get_logger

logger = get_logger(__name__)
DatabaseService.init()

async def populate_esprits_with_updates():
    """Load Esprit base data from JSON file, UPDATING existing entries."""
    json_file = Path("data/config/esprits.json")
    
    if not json_file.exists():
        logger.error(f"Error: {json_file} not found!")
        return
    
    logger.info(f"Found esprits file: {json_file}")
    
    # Load JSON data
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            esprits_data = data.get('esprits', [])
    except Exception as e:
        logger.error(f"Error loading JSON: {e}")
        return
    
    logger.info(f"Found {len(esprits_data)} esprits to process")
    
    # Track statistics
    added = 0
    updated = 0
    errors = 0
    
    async with DatabaseService.get_transaction() as session:
        for esprit_data in esprits_data:
            try:
                # Check if Esprit already exists
                stmt = select(EspritBase).where(EspritBase.name == esprit_data['name'])
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()
                
                if existing:
                    # UPDATE existing Esprit with new stats
                    existing.element = esprit_data['element']
                    existing.base_tier = esprit_data['base_tier']
                    existing.tier_name = esprit_data.get('tier_name')
                    existing.base_atk = esprit_data['base_atk']
                    existing.base_def = esprit_data['base_def']
                    existing.base_hp = esprit_data['base_hp']
                    existing.description = esprit_data.get('description', '')
                    existing.image_url = esprit_data.get('image_url')
                    
                    logger.info(f"UPDATED {existing.name} with new stats: {existing.base_atk}/{existing.base_def}/{existing.base_hp}")
                    updated += 1
                else:
                    # CREATE new Esprit
                    new_esprit = EspritBase(
                        name=esprit_data['name'],
                        element=esprit_data['element'],
                        base_tier=esprit_data['base_tier'],
                        tier_name=esprit_data.get('tier_name'),
                        base_atk=esprit_data['base_atk'],
                        base_def=esprit_data['base_def'],
                        base_hp=esprit_data['base_hp'],
                        description=esprit_data.get('description', ''),
                        image_url=esprit_data.get('image_url')
                    )
                    
                    session.add(new_esprit)
                    logger.info(f"ADDED {new_esprit.name} (Tier {new_esprit.base_tier})")
                    added += 1
                    
            except Exception as e:
                logger.error(f"Error processing {esprit_data.get('name', 'unknown')}: {e}")
                errors += 1
    
    # Print summary
    print("\n" + "="*25 + " SUMMARY " + "="*25)
    print(f"✅ Added: {added} new esprits")
    print(f"🔄 Updated: {updated} existing esprits")
    print(f"❌ Errors: {errors}")
    print("="*59)
    
    # Verify some updated stats
    if updated > 0 or added > 0:
        print("\n📋 Sample Esprit stats from DB:")
        async with DatabaseService.get_session() as session:
            stmt = select(EspritBase).limit(5)
            result = await session.execute(stmt)
            sample_esprits = result.scalars().all()
            
            for esprit in sample_esprits:
                print(f"  • {esprit.name} - {esprit.element} ({esprit.base_atk}/{esprit.base_def}/{esprit.base_hp})")

if __name__ == "__main__":
    asyncio.run(populate_esprits_with_updates())