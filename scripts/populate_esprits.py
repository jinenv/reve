#!/usr/bin/env python3
"""
Script to populate the Esprit table from a JSON file.
This handles initial data loading and updates for the esprit collection.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List, Any

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import select
from src.models import Esprit, ElementType
from src.utils.database_service import DatabaseService
from src.utils.logger import get_logger

logger = get_logger(__name__)

async def populate_esprits():
    """Load esprits from JSON file into database."""
    # File paths
    json_file = Path("data/config/esprits.json")
    
    # Check if file exists
    if not json_file.exists():
        print(f"❌ Error: {json_file} not found!")
        print(f"   Looking in: {json_file.absolute()}")
        return
    
    print(f"✅ Found esprits file: {json_file}")
    
    # Load JSON data
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            esprits_data = data.get('esprits', [])
    except Exception as e:
        print(f"❌ Error loading JSON: {e}")
        return
    
    print(f"📊 Found {len(esprits_data)} esprits to load")
    
    # Statistics
    added = 0
    skipped = 0
    errors = 0
    
    # Process each esprit
    async with DatabaseService.get_transaction() as session:
        for esprit_data in esprits_data:
            try:
                # Check if esprit already exists
                stmt = select(Esprit).where(Esprit.name == esprit_data['name'])
                existing = await session.execute(stmt)
                existing_esprit = existing.scalar_one_or_none()
                
                if existing_esprit:
                    print(f"⚠️  Skipped {esprit_data['name']} (already exists)")
                    skipped += 1
                    continue
                
                # Map element name to enum
                element_map = {
                    'Inferno': ElementType.INFERNO,
                    'Abyssal': ElementType.ABYSSAL,
                    'Umbral': ElementType.UMBRAL,
                    'Verdant': ElementType.VERDANT,
                    'Radiant': ElementType.RADIANT,
                    'Tempest': ElementType.TEMPEST
                }
                
                element = element_map.get(esprit_data['element'])
                if not element:
                    print(f"❌ Unknown element: {esprit_data['element']} for {esprit_data['name']}")
                    errors += 1
                    continue
                
                # Create new esprit - using the correct field names!
                new_esprit = Esprit(
                    name=esprit_data['name'],
                    tier=esprit_data['tier'],
                    element=element,
                    base_attack=esprit_data['base_attack'],      # Changed from base_atk
                    base_defense=esprit_data['base_defense'],    # Changed from base_def
                    base_hp=esprit_data['base_hp'],              # This one stays the same
                    description=esprit_data.get('description', ''),
                    image_url=esprit_data.get('image_url'),
                    leader_effect_name=esprit_data.get('leader_effect_name'),
                    leader_effect_description=esprit_data.get('leader_effect_description'),
                    leader_effect_value=esprit_data.get('leader_effect_value', 0)
                )
                
                session.add(new_esprit)
                print(f"✅ Added {new_esprit.name} (Tier {new_esprit.tier}, {element.value})")
                added += 1
                
            except Exception as e:
                print(f"❌ Error processing {esprit_data.get('name', 'unknown')}: {e}")
                errors += 1
    
    # Display summary
    print("\n🎉 DONE!")
    print(f"✅ Added: {added} esprits")
    print(f"⚠️  Skipped: {skipped} esprits")
    print(f"❌ Errors: {errors}")
    
    # Show some tier 1 esprits as verification (in a new transaction)
    if added > 0:
        print("\n📋 Sample Tier 1 Esprits:")
        async with DatabaseService.get_transaction() as session:
            stmt = select(Esprit).where(Esprit.tier == 1).limit(6)
            result = await session.execute(stmt)
            tier1_esprits = result.scalars().all()
            
            for esprit in tier1_esprits:
                print(f"   • {esprit.name} - {esprit.element.value} ({esprit.base_attack} ATK / {esprit.base_defense} DEF)")

if __name__ == "__main__":
    asyncio.run(populate_esprits())