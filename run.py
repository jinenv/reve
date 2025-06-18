# run.py
import os
import sys
# Add src/ to Python path so we can import src.main
project_root = os.path.dirname(__file__)
src_path = os.path.join(project_root, "src")
sys.path.insert(0, os.path.abspath(src_path))

from main import main

if __name__ == "__main__":
    main()

