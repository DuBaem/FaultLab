import sys
from pathlib import Path

# baseline.py, server.py, and client.py each live in their own folder rather
# than a proper package, so point the test path at each directly instead of
# restructuring the project.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "baseline"))
sys.path.insert(0, str(REPO_ROOT / "server"))
sys.path.insert(0, str(REPO_ROOT / "client"))
# reset.py lives at the repo root, so make sure it's importable too
# regardless of how pytest happens to be invoked.
sys.path.insert(0, str(REPO_ROOT))
