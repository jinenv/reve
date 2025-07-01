#!/usr/bin/env python3
# run_bot.py - Unicode-Safe Bot Launcher for Windows
"""
Unicode-safe bot launcher that ensures proper console encoding on Windows.
Use this instead of running bot.py directly to avoid Unicode issues.
"""

import os
import sys
import subprocess
from pathlib import Path

def setup_windows_unicode():
    """Setup Windows console for Unicode support"""
    if sys.platform == "win32":
        try:
            # Set console code page to UTF-8
            os.system("chcp 65001 >nul 2>&1")
            
            # Set environment variables for UTF-8
            os.environ["PYTHONIOENCODING"] = "utf-8"
            os.environ["PYTHONUTF8"] = "1"
            
            print("✓ Windows console configured for Unicode")
        except Exception as e:
            print(f"⚠ Warning: Could not fully configure Unicode support: {e}")
            print("  This might cause emoji display issues in console output")

def main():
    """Main launcher"""
    print("🎮 Jiji Discord Bot Launcher")
    print("=" * 40)
    
    # Setup Unicode support
    setup_windows_unicode()
    
    # Verify bot.py exists
    bot_file = Path("bot.py")
    if not bot_file.exists():
        print("❌ Error: bot.py not found!")
        print("   Make sure you're running this from the project root directory.")
        sys.exit(1)
    
    # Verify virtual environment
    venv_python = Path("venv/Scripts/python.exe" if sys.platform == "win32" else "venv/bin/python")
    if venv_python.exists():
        python_cmd = str(venv_python)
        print(f"✓ Using virtual environment: {python_cmd}")
    else:
        python_cmd = sys.executable
        print(f"⚠ Virtual environment not found, using system Python: {python_cmd}")
    
    # Create logs directory
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    print(f"✓ Logs directory ready: {logs_dir}")
    
    # Check for .env file
    env_file = Path(".env")
    if env_file.exists():
        print("✓ Environment file found")
    else:
        print("⚠ .env file not found - make sure DISCORD_TOKEN is set")
    
    print("\n🚀 Starting Jiji bot...")
    print("   Press Ctrl+C to stop the bot")
    print("-" * 40)
    
    try:
        # Run the bot with proper encoding
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        
        # Use subprocess to maintain proper encoding
        result = subprocess.run(
            [python_cmd, "bot.py"],
            env=env,
            text=True,
            encoding="utf-8"
        )
        
        if result.returncode != 0:
            print(f"\n❌ Bot exited with code {result.returncode}")
        else:
            print("\n✓ Bot shutdown gracefully")
            
    except KeyboardInterrupt:
        print("\n\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"\n❌ Error running bot: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()