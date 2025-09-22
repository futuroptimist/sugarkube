# token.place Sample Datasets

Sugarkube images now bundle HTTP request samples so operators can validate
`token.place` before exposing the cluster. The payloads live alongside the
source tree under [`samples/token_place/`](../samples/token_place/) and the build
pipeline copies them into two runtime locations:

- `/opt/projects/token.place/samples/` inside the token.place workspace
- `/opt/sugarkube/samples/token-place/` next to the helper scripts

## Contents

| Artifact | Description |
| --- | --- |
| `openai-chat-demo.json` | OpenAI-compatible chat completion body that exercises the bundled mock model. |
| `postman/tokenplace-first-boot.postman_collection.json` | Postman collection with health, model list, and chat requests using the `{{baseUrl}}` variable. |
| `http/tokenplace-quickcheck.http` | VS Code REST Client snippet mirroring the Postman requests. |

The sample chat request expects the mock model to respond. Set `USE_MOCK_LLM=1`
in `/opt/projects/token.place/.env` when you need deterministic replies during
demos.

## Automated replay script

`/opt/sugarkube/token_place_replay_samples.py` reads the JSON payload and issues
three probes against the relay:

1. `GET /v1/health`
2. `GET /v1/models`
3. `POST /v1/chat/completions`

The script falls back to the `/api/v1/*` paths automatically and writes the
responses to `~/sugarkube/reports/token-place-samples/`.

Run it locally with the `make` or `just` wrappers:

```sh
make token-place-samples
# or
just token-place-samples
```

Pass `TOKEN_PLACE_SAMPLE_ARGS="--dry-run"` (or `TOKEN_PLACE_URL` / `--base-url`)
when targeting a different host.
