#!/usr/bin/env python3
import json, sys
from pathlib import Path
try:
 from jsonschema import validate, Draft202012Validator
except Exception as e:
 print("Missing dependency: jsonschema. Install with: pip install jsonschema", file=sys.stderr)
 sys.exit(2)

schema_path = Path("outages/schema.json")
if not schema_path.exists():
 print("schema.json not found at outages/schema.json", file=sys.stderr)
 sys.exit(2)

schema = json.loads(schema_path.read_text())
ok = True
for p in [Path(x) for x in sys.argv[1:]]:
 try:
     data = json.loads(Path(p).read_text())
     validate(data, schema, cls=Draft202012Validator)
     print(f"OK  {p}")
 except Exception as e:
     ok = False
     print(f"FAIL {p}: {e}", file=sys.stderr)
sys.exit(0 if ok else 1)
