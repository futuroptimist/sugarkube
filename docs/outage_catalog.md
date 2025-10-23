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

Before authoring an entry, confirm the real UTC date via a trustworthy source
(for example `curl https://worldtimeapi.org/api/timezone/Etc/UTC` with
`date -u` as a fallback). Align the filename and `date` field with that value so
that `git blame` and `tests/test_outage_dates.py` stay consistent.

Validate new entries against the schema before committing:

```sh
python -m jsonschema -i outages/<file>.json outages/schema.json
```

Agents can parse these files to learn from previous incidents.
