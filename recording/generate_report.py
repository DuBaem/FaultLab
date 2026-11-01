
import json
from pathlib import Path

from recording.aggregate_results import aggregate_experiments


BASE = Path("results/experiments")

pairs = [
    (
        BASE / "server-latency-demo-20261101T040333Z-1dcc2022",
        BASE / "server-latency-demo-20261101T040622Z-495005fe",
    ),
    (
        BASE / "server-latency-demo-20261101T043404Z-8471ce1a",
        BASE / "server-latency-demo-20261101T043509Z-48d50f52",
    ),
    (
        BASE / "server-latency-demo-20261101T152010Z-a904422a",
        BASE / "server-latency-demo-20261101T152215Z-f4dd7d53",
    ),
]

report = aggregate_experiments(pairs)

output_path = Path("results/reproducibility_report.json")
output_path.parent.mkdir(parents=True, exist_ok=True)

output_path.write_text(
    json.dumps(report, indent=2) + "\n",
    encoding="utf-8",
)

print(json.dumps(report, indent=2))
print(f"\nReport saved to: {output_path}")
