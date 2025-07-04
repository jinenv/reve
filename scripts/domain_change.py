#!/usr/bin/env python3
"""
Simple script to rollback domain changes:
- revies → jijies  
- reve → jiji
- 12 tiers → 18 tiers
"""

import os
import re
import sys
from pathlib import Path

def rollback_file_content(file_path):
    """Rollback domain changes in a single file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # Currency changes
        content = re.sub(r'\brevies\b', 'jijies', content)
        content = re.sub(r'\bRevies\b', 'Jijies', content) 
        content = re.sub(r'\bREVIES\b', 'JIJIES', content)
        content = re.sub(r'total_revies_earned', 'total_jijies_earned', content)
        
        # Bot name changes
        content = re.sub(r'\breve\b', 'jiji', content)
        content = re.sub(r'\bReve\b', 'Jiji', content)
        content = re.sub(r'\bREVE\b', 'JIJI', content)
        
        # Tier system changes
        content = re.sub(r'MAX_TIER = 12', 'MAX_TIER = 18', content)
        content = re.sub(r'max_tier.*?12', 'max_tier": 18', content)
        content = re.sub(r'tier <= 12', 'tier <= 18', content)
        content = re.sub(r'1 <= tier <= 12', '1 <= tier <= 18', content)
        
        # Database column references
        content = re.sub(r'"ix_player_revies"', '"ix_player_jijies"', content)
        
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        return False
        
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False

def main():
    """Main rollback function"""
    
    # Get current working directory (where script is run from)
    project_root = Path.cwd()
    
    print(f"Current directory: {project_root}")
    
    # Look for Python files to confirm this is the right place
    python_files = list(project_root.glob("**/*.py"))
    if not python_files:
        print("No Python files found! Are you in the right directory?")
        sys.exit(1)
    
    print(f"Found {len(python_files)} Python files")
    
    # Check if this looks like your project
    has_models = any("models" in str(f) or "player.py" in str(f) for f in python_files)
    if not has_models:
        print("This doesn't look like your Jiji project directory!")
        print("Make sure you're running from the project root.")
        sys.exit(1)
    
    print("🔄 Rolling back domain changes...")
    
    # Files to process
    file_patterns = [
        "src/**/*.py",
        "data/**/*.json",
        "*.md",
        "requirements.txt"
    ]
    
    files_changed = 0
    total_files = 0
    
    for pattern in file_patterns:
        for file_path in project_root.glob(pattern):
            if file_path.is_file():
                total_files += 1
                if rollback_file_content(file_path):
                    files_changed += 1
                    print(f"✅ Updated: {file_path.relative_to(project_root)}")
    
    print(f"\n📊 Rollback complete!")
    print(f"Files processed: {total_files}")
    print(f"Files changed: {files_changed}")
    
    print("\n⚠️  Manual steps still needed:")
    print("1. Run database migration to rename columns:")
    print("   ALTER TABLE player RENAME COLUMN revies TO jijies;")
    print("   ALTER TABLE player RENAME COLUMN total_revies_earned TO total_jijies_earned;")
    print("2. Update game_constants.py tier definitions manually")
    print("3. Clear Redis cache")
    print("4. Test bot functionality")

if __name__ == "__main__":
    main()