import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path so that imports like `from models.xxx import yyy` work.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


@pytest.fixture
def tmp_project_dir(tmp_path: Path) -> Path:
    """Create an isolated temporary directory with a minimal MWU-like structure.

    The directory is seeded with a ``resource/`` subdirectory and an otherwise
    empty layout suitable for testing interface loading, path resolution, etc.
    """
    project_dir = tmp_path / "mwu_project"
    project_dir.mkdir()
    (project_dir / "resource").mkdir()
    return project_dir


@pytest.fixture
def sample_interface() -> dict:
    """Return a minimal valid interface.json dict suitable for testing."""
    return {
        "interface_version": 2,
        "name": "TestGame",
        "label": "Test Game",
        "controller": [
            {
                "name": "AdbController",
                "type": "Adb",
            },
        ],
        "resource": [
            {
                "name": "main",
                "path": ["resource"],
            },
        ],
        "task": [
            {
                "name": "Startup",
                "entry": "EntryStartup",
            },
        ],
        "option": {
            "difficulty": {
                "type": "select",
                "label": "Difficulty",
                "cases": [
                    {"name": "easy", "label": "Easy"},
                    {"name": "hard", "label": "Hard"},
                ],
                "default_case": "easy",
            },
        },
    }
