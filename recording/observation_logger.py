
import json
from pathlib import Path
from datetime import datetime, timezone


def save_observations(run_dir, observations):
    """
    Save application request observations for one
    FaultLab experiment.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    run_id = run_dir.name

    data = {
        "run_id": run_id,
        "recorded_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "request_count": len(observations),
        "observations": observations
    }

    output_path = run_dir / "observations.json"

    output_path.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )

    return output_path
