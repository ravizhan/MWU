import sys
from pathlib import Path

# Ensure project root is on sys.path so that imports like `from models.xxx import yyy` work.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
