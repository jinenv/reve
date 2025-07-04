#!/usr/bin/env python3
"""
Aggressive Jiji → Reve converter that will catch everything VS Code found.
Uses simple string replacement to ensure we get all instances.
"""

import os
import sys
from pathlib import Path

def aggressive_fix_file(file_path: Path) -> bool:
    """Aggressively fix all jiji references using simple string replacement"""
    try:
        # Skip binary files and certain extensions
        skip_extensions = {'.pyc', '.pyo', '.pyd', '.so', '.dll', '.exe', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.zip', '.tar', '.gz'}
        if file_path.suffix.lower() in skip_extensions:
            return False
            
        # Read file content
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            # Skip binary files
            return False
        
        original_content = content
        
        # Simple string replacements - be very explicit
        # Start with most specific to avoid conflicts
        
        # Preserve "revies" (currency) - handle cases where it might have been corrupted
        content = content.replace('reveis', 'revies')  # Fix if corruption happened
        content = content.replace('Reveis', 'Revies')
        content = content.replace('REVEIS', 'REVIES')
        
        # Now do jiji → reve conversions
        # Handle whole words first
        replacements = [
            # Exact matches with word boundaries (manual implementation)
            ('jiji ', 'reve '),
            ('jiji\n', 'reve\n'),
            ('jiji\t', 'reve\t'),
            ('jiji)', 'reve)'),
            ('jiji}', 'reve}'),
            ('jiji]', 'reve]'),
            ('jiji"', 'reve"'),
            ("jiji'", "reve'"),
            ('jiji,', 'reve,'),
            ('jiji.', 'reve.'),
            ('jiji:', 'reve:'),
            ('jiji;', 'reve;'),
            ('jiji/', 'reve/'),
            ('jiji\\', 'reve\\'),
            ('jiji-', 'reve-'),
            ('jiji_', 'reve_'),
            ('"jiji"', '"reve"'),
            ("'jiji'", "'reve'"),
            ('(jiji)', '(reve)'),
            ('[jiji]', '[reve]'),
            ('{jiji}', '{reve}'),
            
            # Title case
            ('Jiji ', 'Reve '),
            ('Jiji\n', 'Reve\n'),
            ('Jiji\t', 'Reve\t'),
            ('Jiji)', 'Reve)'),
            ('Jiji}', 'Reve}'),
            ('Jiji]', 'Reve]'),
            ('Jiji"', 'Reve"'),
            ("Jiji'", "Reve'"),
            ('Jiji,', 'Reve,'),
            ('Jiji.', 'Reve.'),
            ('Jiji:', 'Reve:'),
            ('Jiji;', 'Reve;'),
            ('Jiji/', 'Reve/'),
            ('Jiji\\', 'Reve\\'),
            ('Jiji-', 'Reve-'),
            ('Jiji_', 'Reve_'),
            ('"Jiji"', '"Reve"'),
            ("'Jiji'", "'Reve'"),
            ('(Jiji)', '(Reve)'),
            ('[Jiji]', '[Reve]'),
            ('{Jiji}', '{Reve}'),
            
            # Uppercase
            ('JIJI ', 'REVE '),
            ('JIJI\n', 'REVE\n'),
            ('JIJI\t', 'REVE\t'),
            ('JIJI)', 'REVE)'),
            ('JIJI}', 'REVE}'),
            ('JIJI]', 'REVE]'),
            ('JIJI"', 'REVE"'),
            ("JIJI'", "REVE'"),
            ('JIJI,', 'REVE,'),
            ('JIJI.', 'REVE.'),
            ('JIJI:', 'REVE:'),
            ('JIJI;', 'REVE;'),
            ('JIJI/', 'REVE/'),
            ('JIJI\\', 'REVE\\'),
            ('JIJI-', 'REVE-'),
            ('JIJI_', 'REVE_'),
            ('"JIJI"', '"REVE"'),
            ("'JIJI'", "'REVE'"),
            ('(JIJI)', '(REVE)'),
            ('[JIJI]', '[REVE]'),
            ('{JIJI}', '{REVE}'),
            
            # Special cases at start of string
            ('jiji', 'reve'),  # This will catch remaining cases but do it last
            ('Jiji', 'Reve'),
            ('JIJI', 'REVE'),
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
    """Main aggressive fix function"""
    
    project_root = Path.cwd()
    
    print("🚀 AGGRESSIVE JIJI → REVE CONVERTER")
    print("=" * 50)
    print(f"📁 Project directory: {project_root}")
    
    # Get ALL files (except some obvious skips)
    skip_dirs = {'.git', '__pycache__', '.vscode', 'node_modules', '.pytest_cache'}
    skip_files = {'domain_change.py', 'jiji_to_reve_fixer.py', 'aggressive_jiji_fixer.py'}  # Don't modify our own scripts
    
    all_files = []
    for root, dirs, files in os.walk(project_root):
        # Skip certain directories
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        
        for file in files:
            file_path = Path(root) / file
            if file not in skip_files:
                all_files.append(file_path)
    
    files_changed = 0
    total_files = len(all_files)
    
    print(f"📊 Found {total_files} files to check")
    print("\n🔄 Aggressively converting all Jiji references...")
    
    for file_path in all_files:
        if aggressive_fix_file(file_path):
            files_changed += 1
            print(f"✅ Fixed: {file_path.relative_to(project_root)}")
    
    print(f"\n📈 AGGRESSIVE CONVERSION COMPLETE!")
    print("=" * 50)
    print(f"📊 Files checked: {total_files}")
    print(f"📝 Files modified: {files_changed}")
    
    if files_changed > 0:
        print(f"\n🎉 Successfully converted {files_changed} files!")
        print("\n🔍 Search for 'jiji' in VS Code again - should be much fewer results!")
    else:
        print("\nℹ️  No files needed changes.")
    
    print("\n⚠️  NOTE: You may want to rename your project folder from 'jiji' to 'reve' as well!")

if __name__ == "__main__":
    main()