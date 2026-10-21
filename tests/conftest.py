import sys
from pathlib import Path

# baseline.py lives in its own folder rather than a proper package, so point
# the test path at it directly instead of restructuring the project.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "baseline"))
