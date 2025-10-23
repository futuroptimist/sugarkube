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

### Record accurate dates

- Fetch the current UTC date from a trusted source before drafting the file:

  ```sh
  curl -fsS https://worldtimeapi.org/api/timezone/Etc/UTC | jq -r '.utc_datetime'
  # fallback when offline
  date -u +%F
  ```

- Stamp the outage `date` field and filename prefix with that value.
- After writing the entry, run `git blame` on the `"date"` line to confirm the
  metadata matches what Git recorded.

Agents can parse these files to learn from previous incidents.
