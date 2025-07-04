#!/usr/bin/env python3
"""
Complete Jiji → Reve domain migration script:
- jijies → revies  
- jiji → reve
- Maintains 12-tier system
- Updates all project files
"""

import os
import re
import sys
import json
from pathlib import Path
from typing import Dict, Any, List

def migrate_file_content(file_path: Path) -> bool:
    """Apply forward domain migration to a single file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # Currency changes: jijies → revies
        content = re.sub(r'\bjijies\b', 'revies', content)
        content = re.sub(r'\bJijies\b', 'Revies', content) 
        content = re.sub(r'\bJIJIES\b', 'REVIES', content)
        content = re.sub(r'total_jijies_earned', 'total_revies_earned', content)
        
        # Bot name changes: jiji → reve
        content = re.sub(r'\bjiji\b', 'reve', content)
        content = re.sub(r'\bJiji\b', 'Reve', content)
        content = re.sub(r'\bJIJI\b', 'REVE', content)
        
        # Service class names
        content = re.sub(r'ReviesService', 'ReviesService', content)  # Keep ReviesService name for consistency
        content = re.sub(r'JijiJSONEncoder', 'ReveJSONEncoder', content)
        
        # Database column references  
        content = re.sub(r'"ix_player_jijies"', '"ix_player_revies"', content)
        content = re.sub(r'player\.jijies', 'player.revies', content)
        content = re.sub(r'Player\.jijies', 'Player.revies', content)
        
        # Comments and documentation
        content = re.sub(r'Jiji domain economy', 'Reve domain economy', content)
        content = re.sub(r'jijies transition', 'revies transition', content)
        
        # Configuration keys
        content = re.sub(r'"jijies":', '"revies":', content)
        content = re.sub(r"'jijies':", "'revies':", content)
        content = re.sub(r'{"jijies"', '{"revies"', content)
        
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        return False
        
    except Exception as e:
        print(f"❌ Error processing {file_path}: {e}")
        return False

def convert_esprit_tier(tier: int) -> int:
    """Convert 18-tier system to 12-tier system"""
    # Tier conversion mapping
    tier_mapping = {
        # Keep tiers 1-12 as-is
        1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6,
        7: 7, 8: 8, 9: 9, 10: 10, 11: 11, 12: 12,
        # Map tiers 13-18 to appropriate 12-tier equivalents
        13: 10,  # Absolute → Empyrean (T10)
        14: 11,  # Astral → Void (T11) 
        15: 11,  # Celestial → Void (T11)
        16: 12,  # Primal → Singularity (T12)
        17: 12,  # Sovereign → Singularity (T12)
        18: 12   # Transcendent → Singularity (T12)
    }
    return tier_mapping.get(tier, min(tier, 12))

def get_new_tier_name(tier: int) -> str:
    """Get new tier name for converted tier"""
    tier_names = {
        1: "common", 2: "uncommon", 3: "rare", 4: "epic", 5: "mythic", 6: "divine",
        7: "legendary", 8: "ethereal", 9: "genesis", 10: "empyrean", 11: "void", 12: "singularity"
    }
    return tier_names.get(tier, "unknown")

def migrate_esprits_json(file_path: Path) -> bool:
    """Migrate esprits.json from 18-tier to 12-tier system"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Handle both dictionary with "esprits" key and direct list formats
        esprits_data = None
        is_dict_format = False
        
        if isinstance(data, dict) and "esprits" in data:
            esprits_data = data["esprits"]
            is_dict_format = True
        elif isinstance(data, list):
            esprits_data = data
            is_dict_format = False
        else:
            print(f"❌ Expected list or dict with 'esprits' key in {file_path}, got {type(data)}")
            return False
        
        if not isinstance(esprits_data, list):
            print(f"❌ Expected 'esprits' to be a list, got {type(esprits_data)}")
            return False
        
        conversions = []
        
        for esprit in esprits_data:
            if 'base_tier' in esprit:
                old_tier = esprit['base_tier']
                new_tier = convert_esprit_tier(old_tier)
                
                if old_tier != new_tier:
                    conversions.append({
                        'name': esprit.get('name', 'Unknown'),
                        'old_tier': old_tier,
                        'new_tier': new_tier,
                        'old_tier_name': esprit.get('tier_name', 'unknown'),
                        'new_tier_name': get_new_tier_name(new_tier)
                    })
                
                # Update the esprit
                esprit['base_tier'] = new_tier
                esprit['tier_name'] = get_new_tier_name(new_tier)
                
                # Update image paths if they reference old tier folders
                if 'image_url' in esprit and esprit['image_url']:
                    old_path = esprit['image_url']
                    # Replace old tier folder names in paths
                    old_tier_folders = ["absolute", "astral", "celestial", "primal", "sovereign", "transcendent"]
                    for old_folder in old_tier_folders:
                        if f"/{old_folder}/" in old_path:
                            new_path = old_path.replace(f"/{old_folder}/", f"/{get_new_tier_name(new_tier)}/")
                            esprit['image_url'] = new_path
                            break
                
                # Update portrait URLs similarly
                if 'portrait_url' in esprit and esprit['portrait_url']:
                    old_path = esprit['portrait_url']
                    old_tier_folders = ["absolute", "astral", "celestial", "primal", "sovereign", "transcendent"]
                    for old_folder in old_tier_folders:
                        if f"/{old_folder}/" in old_path:
                            new_path = old_path.replace(f"/{old_folder}/", f"/{get_new_tier_name(new_tier)}/")
                            esprit['portrait_url'] = new_path
                            break
        
        # Write back the updated data
        if is_dict_format:
            # Create new dictionary with updated esprits
            output_data = {}
            for key, value in data.items():
                if key == "esprits":
                    output_data[key] = esprits_data
                else:
                    output_data[key] = value
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
        else:
            # Write as direct list
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(esprits_data, f, indent=2, ensure_ascii=False)
        
        if conversions:
            print(f"\n📊 Esprit Tier Conversions ({len(conversions)} total):")
            for conv in conversions:
                print(f"  • {conv['name']}: T{conv['old_tier']} ({conv['old_tier_name']}) → T{conv['new_tier']} ({conv['new_tier_name']})")
        
        return len(conversions) > 0
        
    except Exception as e:
        print(f"❌ Error migrating esprits.json: {e}")
        return False

def main():
    """Main migration function"""
    
    # Get current working directory (where script is run from)
    project_root = Path.cwd()
    
    print("🚀 JIJI → REVE DOMAIN MIGRATION")
    print("=" * 50)
    print(f"📁 Project directory: {project_root}")
    
    # Validate this is the right directory
    python_files = list(project_root.glob("**/*.py"))
    if not python_files:
        print("❌ No Python files found! Are you in the right directory?")
        sys.exit(1)
    
    # Check if this looks like your project
    has_models = any("models" in str(f) or "player.py" in str(f) for f in python_files)
    if not has_models:
        print("❌ This doesn't look like your project directory!")
        print("Make sure you're running from the project root.")
        sys.exit(1)
    
    print(f"📊 Found {len(python_files)} Python files")
    
    # File patterns to process for domain migration
    file_patterns = [
        "src/**/*.py",
        "data/**/*.json", 
        "*.md",
        "requirements.txt",
        "alembic.ini"
    ]
    
    # Special handling for esprits.json
    esprits_file = project_root / "data" / "config" / "esprits.json"
    
    files_changed = 0
    total_files = 0
    esprit_conversions = 0
    
    print("\n🔄 Processing domain migration...")
    
    # Handle esprits.json tier conversion first
    if esprits_file.exists():
        print(f"\n🎯 Converting esprits.json tier system...")
        if migrate_esprits_json(esprits_file):
            esprit_conversions += 1
            print(f"✅ Converted: {esprits_file.relative_to(project_root)}")
        else:
            print(f"ℹ️  No tier conversions needed: {esprits_file.relative_to(project_root)}")
    else:
        print(f"⚠️  esprits.json not found at expected location: {esprits_file}")
    
    # Process all other files for domain migration
    for pattern in file_patterns:
        for file_path in project_root.glob(pattern):
            if file_path.is_file() and file_path != esprits_file:  # Skip esprits.json (already handled)
                total_files += 1
                if migrate_file_content(file_path):
                    files_changed += 1
                    print(f"✅ Updated: {file_path.relative_to(project_root)}")
    
    print(f"\n📈 MIGRATION COMPLETE!")
    print("=" * 50) 
    print(f"📊 Files processed: {total_files}")
    print(f"📝 Files changed: {files_changed}")
    print(f"🎯 Esprit tier conversions: {esprit_conversions}")
    
    print("\n🔧 REQUIRED MANUAL STEPS:")
    print("1. Database migration:")
    print("   ALTER TABLE player RENAME COLUMN jijies TO revies;")
    print("   ALTER TABLE player RENAME COLUMN total_jijies_earned TO total_revies_earned;")
    print("   UPDATE player SET updated_at = NOW();")
    
    print("\n2. Redis cache cleanup:")
    print("   FLUSHALL  # Clear all cached data")
    
    print("\n3. Asset folder reorganization:")
    print("   Move any assets from old tier folders to new ones:")
    print("   absolute/ → empyrean/ or void/")
    print("   astral/ → void/") 
    print("   celestial/ → void/")
    print("   primal/ → singularity/")
    print("   sovereign/ → singularity/")
    print("   transcendent/ → singularity/")
    
    print("\n4. Testing:")
    print("   • Test bot startup")
    print("   • Test currency operations")
    print("   • Test esprit display/battles")
    print("   • Verify tier conversions")
    
    print("\n✨ Welcome to the Reve domain! ✨")

if __name__ == "__main__":
    main()