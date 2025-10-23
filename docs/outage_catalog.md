# Outage Catalog

Structured archive of past outages. Each outage is stored as a JSON file using the schema in [`outages/schema.json`](../outages/schema.json).

File naming: `YYYY-MM-DD-<slug>.json`.

Populate each file with these fields:
- `id`: unique identifier
- `date`: ISO date
- `component`: affected subsystem
- `rootCause`: brief description of failure cause
- `resolution`: how it was fixed
- `references`: array of related links (PRs, issues, docs)

Validate new entries against the schema before committing:

```sh
python -m jsonschema -i outages/<file>.json outages/schema.json
```

Always source the timestamp from a trusted clock:

1. Attempt to fetch `https://worldtimeapi.org/api/timezone/Etc/UTC` and parse the
   `utc_datetime` field.
2. Fall back to `date -u +"%Y-%m-%d"` when the network is unreachable.

Use that value for both the filename prefix and the JSON `date` property, then run
`pytest tests/test_outage_dates.py` to ensure no record slips into the future.

Agents can parse these files to learn from previous incidents.
