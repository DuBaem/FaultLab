
import json
import sys
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

# Locate the project and schema
project_root = Path(__file__).resolve().parents[1]
schema_path = project_root / "recording" / "event_schema.json"

with open(schema_path, encoding="utf-8") as file:
    schema = json.load(file)

validator = Draft202012Validator(
    schema,
    format_checker=FormatChecker()
)

# Accept the path to an events.jsonl file
if len(sys.argv) != 2:
    print("Usage: python recording/test_schema.py <events.jsonl>")
    sys.exit(1)

events_path = Path(sys.argv[1])
passed = 0
failed = 0

with open(events_path, encoding="utf-8") as file:
    for line_number, line in enumerate(file, start=1):
        if not line.strip():
            continue

        try:
            event = json.loads(line)
            errors = list(validator.iter_errors(event))

            if errors:
                failed += 1
                print(f"FAIL: Event on line {line_number}")
                for error in errors:
                    print(f"  - {error.message}")
            else:
                passed += 1
                print(
                    f"PASS: Event {line_number} "
                    f"({event['event_type']})"
                )

        except json.JSONDecodeError as error:
            failed += 1
            print(f"FAIL: Invalid JSON on line {line_number}: {error}")

print(f"\nResults: {passed} passed, {failed} failed")

if failed:
    sys.exit(1)
