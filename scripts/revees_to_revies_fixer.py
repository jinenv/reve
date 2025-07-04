#!/usr/bin/env python3
"""
Fix remaining revees → revies references throughout the project.
This script specifically targets the currency naming inconsistency.
"""

import os
import sys
from pathlib import Path

def fix_revees_to_revies(file_path: Path) -> bool:
    """Fix revees → revies in a single file"""
    try:
        # Skip binary files
        skip_extensions = {'.pyc', '.pyo', '.pyd', '.so', '.dll', '.exe', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.zip', '.tar', '.gz'}
        if file_path.suffix.lower() in skip_extensions:
            return False
            
        # Read file content
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            return False
        
        original_content = content
        
        # Fix all revees variants → revies
        replacements = [
            # Direct replacements
            ('revees', 'revies'),
            ('Revees', 'Revies'), 
            ('REVEES', 'REVIES'),
            
            # Configuration keys and values
            ('"revees"', '"revies"'),
            ("'revees'", "'revies'"),
            ('revees_', 'revies_'),
            ('revees:', 'revies:'),
            ('revees}', 'revies}'),
            ('revees]', 'revies]'),
            ('revees)', 'revies)'),
            ('revees,', 'revies,'),
            
            # Common patterns from your search results
            ('revees_reward', 'revies_reward'),
            ('revees_range', 'revies_range'),
            ('revees_multiplier', 'revies_multiplier'),
            ('bonus_revees', 'bonus_revies'),
            ('base_revees', 'base_revies'),
            ('final_revees', 'final_revies'),
            ('total_revees', 'total_revies'),
            
            # In comments and descriptions
            ('# revees', '# revies'),
            ('* revees', '* revies'),
            ('get("revees"', 'get("revies"'),
            (".get('revees'", ".get('revies'"),
            
            # JSON/config patterns
            ('energy_cost": 5, "revees_reward":', 'energy_cost": 5, "revies_reward":'),
            ('energy_cost": 6, "revees_reward":', 'energy_cost": 6, "revies_reward":'),
            ('energy_cost": 7, "revees_reward":', 'energy_cost": 7, "revies_reward":'),
            ('energy_cost": 8, "revees_reward":', 'energy_cost": 8, "revies_reward":'),
            ('energy_cost": 9, "revees_reward":', 'energy_cost": 9, "revies_reward":'),
            ('energy_cost": 10, "revees_reward":', 'energy_cost": 10, "revies_reward":'),
            ('energy_cost": 11, "revees_reward":', 'energy_cost": 11, "revies_reward":'),
            ('energy_cost": 12, "revees_reward":', 'energy_cost": 12, "revies_reward":'),
            ('energy_cost": 13, "revees_reward":', 'energy_cost": 13, "revies_reward":'),
            ('energy_cost": 14, "revees_reward":', 'energy_cost": 14, "revies_reward":'),
            ('energy_cost": 15, "revees_reward":', 'energy_cost": 15, "revies_reward":'),
            ('energy_cost": 16, "revees_reward":', 'energy_cost": 16, "revies_reward":'),
        ]
        
        # Apply all replacements
        for old, new in replacements:
            content = content.replace(old, new)
        
        # Write back if changed
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        return False
        
    except Exception as e:
        print(f"❌ Error processing {file_path}: {e}")
        return False

def main():
    """Main fix function"""
    
    project_root = Path.cwd()
    
    print("🔧 FIXING REVEES → REVIES CURRENCY REFERENCES")
    print("=" * 50)
    print(f"📁 Project directory: {project_root}")
    
    # Skip certain directories and files
    skip_dirs = {'.git', '__pycache__', '.vscode', 'node_modules', '.pytest_cache', 'venv'}
    skip_files = {'revees_to_revies_fixer.py'}  # Don't modify this script
    
    files_changed = 0
    total_files = 0
    
    print("\n🔄 Scanning for revees references...")
    
    for root, dirs, files in os.walk(project_root):
        # Skip certain directories
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        
        for file in files:
            if file in skip_files:
                continue
                
            file_path = Path(root) / file
            total_files += 1
            
            if fix_revees_to_revies(file_path):
                files_changed += 1
                print(f"✅ Fixed: {file_path.relative_to(project_root)}")
    
    print(f"\n📈 FIX COMPLETE!")
    print("=" * 50)
    print(f"📊 Files checked: {total_files}")
    print(f"📝 Files fixed: {files_changed}")
    
    if files_changed > 0:
        print(f"\n🎉 Successfully fixed {files_changed} files!")
        print("\n🔍 Search for 'revees' again - should be much fewer results!")
        print("💡 The bot should now properly recognize 'revies' currency.")
    else:
        print("\nℹ️  No files needed changes.")

if __name__ == "__main__":
    main()