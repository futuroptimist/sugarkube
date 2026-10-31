# Offline existing-enrollment migration planner

`scripts/ethernet_migration_plan.py` validates an operator-supplied capture and emits a
**read-only plan**, not a safety attestation or permission to execute it. It has no apply
command, discovery, network calls, controller imports, service operations or writes. Run
it as an ordinary user against a previously supplied evidence file. It reads that file
and its pinned repository artifact catalog only; paths inside evidence are never opened.

```bash
python3 scripts/ethernet_migration_plan.py captured-evidence.json
# Or supply the same JSON on standard input:
python3 scripts/ethernet_migration_plan.py - < captured-evidence.json
```

Exit status 0 means the supplied evidence is internally consistent with this narrow
planning contract. Status 2 means refusal, with a fixed diagnostic that does not echo
input contents. Output always sets `authorized_to_execute` to `false`. No evidence is
collected by this command, and a coherent fabricated or stale capture can pass. The tool
cannot authenticate its source, establish current health, inspect a backup, prove mounts,
or detect a change after capture. Retain the original capture privately for review.

## Supported transition and provenance

The sole source is commit `1a9e767257e65470d6c7e732240b592500b6ac46`; the sole target is
PR2914 commit `b320c583a39d9771548bff9cd684bf3c08b82caf`. This planner is a separate draft
stacked on PR2914. Source enrollment must use schema 2, have completed dual numeric and
hostname peer enrollment, be armed, and have no `resolver_view` field. Schema 1 and
numeric-only membership require a separate consensus transition. No such transition is
planned here. Other runtime revisions, including mixtures of these revisions, are refused.

The [pinned catalog](../scripts/migration/resolver-v1-to-directory-v1.json) contains literal
service/hook/YAML bytes and runtime SHA256 values derived from `git show` at those exact
revisions. Its own digest is pinned in the planner. Config JSON uses the historical
`service_files` serialization, retaining the original interface and member order; only
the target adds the descriptor. The old and new rendered examples in
[the fixture directory](../tests/fixtures/ethernet_migration/) were rendered from those
historical implementations, not from a supplied target manifest. For example:

| Artifact | Source SHA256 | Target SHA256 |
| --- | --- | --- |
| Controller | `51f4a7015bc81fd0ea5f58677f6f97ef2d4ac5beab1181d3eb66f83f9ab5558c` | `6acb80dcd38ced32a57792fe8eb7dc5ee6ae05099ed51643813fbf4605752201` |
| Resolver | `eaf2ebebd081fd37d66be3c3df1d4a5a305f65d7bfc472214fc54856166b930a` | See the pinned target catalog |

Source provenance can be checked without executing either historical runtime:

```bash
git show 1a9e767257e65470d6c7e732240b592500b6ac46:scripts/ethernet_mdns_resolver.py | sha256sum
git show b320c583a39d9771548bff9cd684bf3c08b82caf:scripts/ethernet_mdns_resolver.py | sha256sum
```

Exactly five owned files change: the controller, resolver, resolver config, resolver
service and K3s resolver hook. The transport, protocol descriptor, WAL identity reader,
recovery hook, watcher service/timer and kubelet YAML must match the known source bytes
and remain unchanged. Only already-enrolled changed files receive planned fingerprint
transitions. Every other enrollment field and fingerprint is preserved. The old resolver
descriptor is absent; the new one is `resolved-stub-directory-v1` with the exact relative
stub symlink and supplied original directory owner/group. No enrollment is generated or
written; hashes describe the proposed transition for review.

## Evidence contract

[The synthetic capture](../tests/fixtures/ethernet_migration/synthetic-capture.json) is a
complete schema example with fabricated identities and hashes. It is not operational
evidence. The [tests](../tests/test_ethernet_migration_plan.py) exercise valid captures and
refusals. Unknown keys, duplicate JSON keys, missing records and type drift are refused.

- `enrollment_json` contains the exact original JSON text, including all existing
  fingerprints. Do not edit enrollment to manufacture eligibility. The supported
  enrollment fields are enumerated by `ENROLLMENT_KEYS` in the planner.
- `source_revision` selects the sole supported source. `capture_id` is an operator-chosen
  SHA256 identifier for one coherent capture. It must agree across health and backup
  records; this is a consistency check, not a signature or freshness guarantee.
- `observed` must cover exactly every enrollment fingerprint and pinned owned artifact.
  Records contain `kind`, numeric `uid`, `gid`, permission `mode` and `sha256`. Optional
  missing files use `kind: absent` and a null digest. Their root ownership and safe mode
  fields describe the intended entry policy; the separate parent records describe the
  captured existing directories. Present files must be regular, owned by root, and not
  writable by group or others. Symlinks, missing owned files and changed hooks refuse.
- `directories` must cover every ancestor, including `/`, of the captured artifact and
  state paths. Each must be a root-owned directory with a safe mode. Paths must be
  absolute and canonical; aliases and dot segments refuse. `state_metadata` separately
  binds the exact enrollment and journal text to captured regular-file metadata and
  records the absent Node-address journal at the standard state path.
- `identity` repeats the captured machine, database, K3s version and effective systemd
  fingerprints for comparison with enrollment. `layout` supplies the exact relative
  resolved stub link, original directory owner/group, safe directory metadata, and
  exactly the two regular resolver files and two resolved sockets. Socket permissions
  may be writable as in the original resolved layout. This first contract requires
  both sockets, no temporary files, no existing directory-view runtime state, and
  `/run/systemd/resolve/resolv.conf` as the original pod resolver source.
- `health` contains exactly the three original voters and three responding endpoints.
  It binds cluster/member identities, Node names/UIDs, converged annotation/InternalIP,
  dual peer URLs, Ready state, original enrollment marker hashes and matching member
  observations. Each responder must report a successful linearizable read, peer TLS
  and API verification, with no unresolved membership or Node-address intent; these
  remain operator-supplied claims. The membership lock must
  be absent. Member observation digests use sorted compact JSON, as `canonical` defines.
  Marker hashes use the controller's historical sorted JSON serialization instead.
- `backup` binds verified snapshot and original-bundle digests to the same capture,
  cluster, original enrollment bytes and member observations. It does not include
  credentials, backup contents or locations. Verification itself is an operator claim.
- `quiescence` reports a paused timer, idle controller and no mutation in progress.
  `journals` preserves the original incident JSON text and explicitly absent Node-address
  journal. Only a completed healthy-time enrollment incident is supported, including a
  consistent completed membership update. Recovery incidents, any Node-address journal,
  unknown fields and unresolved intents require separate review and are refused.

Output includes the exact owned-file hash changes, descriptors, original member/Node
identities, original enrollment hash and proposed canonical enrollment hash. It commits
to preserved fields/fingerprints and journal text by digest without emitting raw journals,
trust material, unrelated file paths or configuration contents. Canonical output hashes
use UTF-8 sorted compact JSON, without a trailing newline. Input order of object keys does
not affect the plan; exact embedded enrollment and journal bytes intentionally do.

## Remaining gates

Eligibility does not authorize a stop, file replacement, fingerprint rewrite, enrollment,
service activation, migration, merge or deployment. The
[existing migration boundary](ethernet-dhcp-recovery.md#existing-enrollment-migration-boundary)
still applies. A separate reviewed procedure must obtain fresh authenticated proof,
preserve all identities/trust/journals, perform controlled changes one server at a time,
and qualify loaded units, actual read-only mounts, resolved IPC, pod DNS and workloads
before timer resume. Interrupted changes must remain stopped for review.

The surviving-quorum startup guard is unchanged. This is not all-member DHCP recovery.
Offline tests do not qualify real K3s, systemd namespaces, native certificate renewal,
DHCP behavior, staging or production. Both pinned K3s versions, `v1.34.5+k3s1` and
`v1.35.4+k3s1`, retain their separate integration gates. K-339 remains open.
