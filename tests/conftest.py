import sys
from pathlib import Path

# Each Docker service has its own source folder. Make those modules available to pytest.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "baseline"))
sys.path.insert(0, str(REPO_ROOT / "server"))
sys.path.insert(0, str(REPO_ROOT / "client"))
# The reset script lives at the repository root.
sys.path.insert(0, str(REPO_ROOT))
