"""Root conftest.py to configure pytest for the entire test suite."""

import sys
from pathlib import Path

# Add the project root to sys.path to make 'app' importable
repo_root = Path(__file__).parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
