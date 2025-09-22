# token.place Sample Datasets

The sugarkube Pi image now bundles small HTTP request samples so you can verify
`token.place` immediately after the first boot. Import the Postman collection,
run the REST Client snippets, or replay the JSON payloads with
`scripts/token_place_replay_samples.py` to confirm the relay answers requests.

## Contents

- [`openai-chat-demo.json`](./openai-chat-demo.json) — Minimal OpenAI-compatible
  chat completion request that works with the bundled mock model.
- [`postman/tokenplace-first-boot.postman_collection.json`](./postman/tokenplace-first-boot.postman_collection.json)
  — Postman collection with health, models, and chat probes using the
  `{{baseUrl}}` variable.
- [`http/tokenplace-quickcheck.http`](./http/tokenplace-quickcheck.http) — VS
  Code REST Client snippet mirroring the Postman requests.

Each Pi image copies this folder to both `/opt/projects/token.place/samples` and
`/opt/sugarkube/samples/token-place`. The replay script stores results under
`~/sugarkube/reports/token-place-samples/` by default.

## Usage

1. Ensure `projects-compose.service` is running on the Pi so `token.place` is
   available on port 5000.
2. Run the helper script:
   ```sh
   /opt/sugarkube/token_place_replay_samples.py
   ```
3. Inspect the generated health/model/chat JSON files in the reports directory.
   The chat response should include "Mock response" when the mock LLM is
   enabled.

Set `TOKEN_PLACE_URL` or pass `--base-url` to target a different host. Use
`--dry-run` to simply validate that the sample payloads are present.
