
import json
from pathlib import Path
from jsonschema import validate, ValidationError

# Find the folder containing this script
folder = Path(__file__).parent

# Load the schema
with open(folder / "event_schema.json") as file:
    schema = json.load(file)

# Load the sample event
with open(folder / "sample_event.json") as file:
    event = json.load(file)

# Check whether the event follows the schema
try:
    validate(instance=event, schema=schema)
    print("SUCCESS: Event follows the FaultLab schema!")
except ValidationError as error:
    print("FAILED:", error.message)
