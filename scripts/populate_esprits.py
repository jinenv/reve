"""
Script to populate the EspritBase table from a JSON file.
This handles initial data loading of all possible Esprits.
"""

import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
# This ensures that 'src' can be found when running the script directly
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import select
# Correctly import the EspritBase model from its actual location
from src.database.models import EspritBase
from src.utils.database_service import DatabaseService
from src.utils.logger import get_logger

# Initialize services needed for the script to run
logger = get_logger(__name__)
DatabaseService.init()

async def populate_esprits():
    """Load Esprit base data from JSON file into the database."""
    # The path to your Esprits data file
    json_file = Path("data/config/esprits.json")
    
    # Check if the data file exists
    if not json_file.exists():
        logger.error(f"Error: {json_file} not found!")
        logger.error(f"Looking in: {json_file.absolute()}")
        return
    
    logger.info(f"Found esprits file: {json_file}")
    
    # Load the JSON data from the file
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            esprits_data = data.get('esprits', [])
    except Exception as e:
        logger.error(f"Error loading JSON: {e}")
        return
    
    logger.info(f"Found {len(esprits_data)} esprits to load")
    
    # Keep track of statistics for the summary
    added = 0
    skipped = 0
    errors = 0
    
    # Use a database transaction to process all Esprits
    async with DatabaseService.get_transaction() as session:
        for esprit_data in esprits_data:
            try:
                # Check if an Esprit with the same name already exists in EspritBase
                stmt = select(EspritBase).where(EspritBase.name == esprit_data['name'])
                existing = await session.execute(stmt)
                
                if existing.scalar_one_or_none():
                    logger.warning(f"Skipped {esprit_data['name']} (already exists)")
                    skipped += 1
                    continue
                
                # Create a new EspritBase object using the correct field names
                # from your src/database/models/esprit_base.py file
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
                logger.info(f"Added {new_esprit.name} (Tier {new_esprit.base_tier}, {new_esprit.element})")
                added += 1
                
            except Exception as e:
                logger.error(f"Error processing {esprit_data.get('name', 'unknown')}: {e}")
                errors += 1
    
    # Print a summary of the operation
    print("\n" + "="*20 + " SUMMARY " + "="*20)
    print(f"✅ Added: {added} esprits")
    print(f"⚠️  Skipped: {skipped} esprits")
    print(f"❌ Errors: {errors}")
    print("="*49)
    
    # As a final verification, query and display some of the added Tier 1 Esprits
    if added > 0:
        print("\n📋 Sample Tier 1 Esprits from DB:")
        async with DatabaseService.get_session() as session:
            stmt = select(EspritBase).where(EspritBase.base_tier == 1).limit(6) # type: ignore
            result = await session.execute(stmt)
            tier1_esprits = result.scalars().all()
            
            for esprit in tier1_esprits:
                print(f"  • {esprit.name} - {esprit.element} ({esprit.base_atk} ATK / {esprit.base_def} DEF)")

if __name__ == "__main__":
    asyncio.run(populate_esprits())