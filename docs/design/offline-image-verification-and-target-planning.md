# Sugarkube offline image verification and target planning

K106 design proposal for review

Source snapshot 2587b93ab1843a67beb6f2a553b9d159be8f3767

Prepared 12 October 2026

## Recommended first slice

Adopt a pure offline verifier and target planner before integrating any downloader, installer or
flashing command. The core receives bounded byte strings and synthetic device records, returns a
reviewable result, and has no network, subprocess, device or filesystem capabilities. This PR
documents that contract only. Implementation, acquisition and physical-media qualification each
require a later, separately bounded change.

Keep three conclusions separate in every result: publisher authentication, compressed and expanded
byte consistency, and target eligibility. A checksum establishes consistency with its reference. A
verified signature establishes an allowed signing identity. Neither establishes that a physical
drive is the operator's intended drive.

The first synthetic host profile is native Linux x86_64. The first target profile is a whole
removable microSD card on a native SD/MMC reader that exposes a card CID and complete topology.
Restrict the initial profile to 512-byte logical sectors. The payload family is the project's ARM64
Raspberry Pi OS image; boot compatibility with a particular Pi model is not established by this
planner. These are proposed boundaries, not a claim that a live host or card has been tested.

This is intentionally a narrow starting point. Native SD/MMC exposes a card identification register,
which the proposed profile uses as a medium-specific identifier. Common USB readers may identify the
reader instead of the inserted card, so a reader serial alone is insufficient. macOS, Windows, WSL,
USB readers, USB SSDs, NVMe, multi-LUN readers, multipath devices and built-in system disks remain
unsupported until their own topology and physical-identity contracts are reviewed. Linux source
already has discovery and identifier tests, while the current cross-platform flasher's
platform-specific protections differ. [S4](#s4) [S9](#s9) [S17](#s17)

## Current source findings

These findings describe the pinned source snapshot below. They are source observations, not
release-asset or physical-device qualification.

The release workflow signs both sugarkube.img.xz and its JSON manifest using Cosign, and publishes
signature and certificate sidecars. Its checked-in commands do not emit a complete offline Sigstore
bundle. The manifest records a compressed-image digest and size, repository commit and ref, workflow
run metadata, and optional QEMU evidence. It has no dedicated signed expanded-image length or
digest. This is a source finding, not an inspection of every existing release asset. [S1](#s1) [S2](#s2)

The downloader verifies the checksum delivered beside the image without consuming the signatures or
enforcing an expected signer and workflow identity. Its auto mode can fall back from a failed
release path to workflow artifacts. The fallback's run listing does not explicitly require a
successful conclusion and its run operations do not explicitly bind the selected repository. A
failed selected release must not silently become a different provenance class in the proposed
contract. [S3](#s3)

The installer fetches the download helper from mutable main unless overridden, then executes it.
Selecting an image release does not pin that helper. The optional local GitHub CLI installation hook
executes before the existing-cli check; the normal bootstrap downloads and installs an archive
without a digest or signature check in that path. Quoted arguments, temporary files and dry-run
output provide operational safeguards but do not authenticate this code. These findings require
control over the distribution/build source, image-plus-checksum replacement, or an intentional local
hook; they do not establish an anonymous remote exploit. [S5](#s5)

The flasher discovers candidate media, prompts, can reject mounted media and reads written bytes
back. Explicit unmatched input becomes a custom removable device with no discovered mount topology.
Its root check warns using Linux major-number comparison, and the image is streamed before its
complete expanded length has been established. The target is reopened by pathname for readback.
Existing mitigations are useful, but an unmatched path, unknown topology or path reuse must not
create target authority. [S4](#s4)

## Trust boundaries

Untrusted inputs include release listings, URLs, asset names, manifests before verification,
certificates and bundles, imported device observations, saved plans, checkpoints and diagnostics.
Treat every field as data. No field may select code, shell fragments, a verifier, a root
certificate, a policy file or an import path.

Trusted inputs are the independently provisioned verifier build, its pinned dependency set, an
operator-reviewed policy and trust-root snapshot, and an explicit evaluation time. The proposed
production policy is separate from imported release files and cannot be replaced by them. A
compromised host, malicious firmware, compromised approved signer/workflow, or operator selection of
the wrong physical card remains outside the guarantees of this core. Identifiers help prevent
accidental target substitution; they are not cryptographic proof of hardware identity.

The proposed verifier authenticates what an approved publisher signed. It does not prove that the
build was reproducible, that dependencies were safe, that an image will boot, or that the final
system is secure. QEMU evidence is useful build evidence and cannot substitute for physical
qualification.

## Publisher policy

Use Sigstore keyless verification with an exact identity allowlist. The proposed production policy
has these fixed identity constraints:

- OIDC issuer: https://token.actions.githubusercontent.com

- Certificate identity:
  https://github.com/futuroptimist/sugarkube/.github/workflows/pi-image-release.yml@refs/heads/main

- Repository: futuroptimist/sugarkube

- GitHub repository ID: 1019977888; owner ID: 80668851

- Workflow path: .github/workflows/pi-image-release.yml

- Workflow ref: refs/heads/main

- Event: workflow_dispatch

- Release channel: stable

Require the verified certificate extensions or equivalent authenticated provenance to bind
repository identity, numerical repository and owner IDs, source ref and full source commit to the
signed manifest. Unsigned API copies cannot supply missing authenticated claims. A missing required
claim, inconsistent representation or unsupported certificate format blocks admission. The future
adapter must map these checks to the verifier's documented Fulcio extension support and validate
that mapping with signed fixtures. No wildcard identity or issuer, fork identity, pull-request ref,
ordinary pi-image.yml signer, nightly release or unsigned workflow artifact is accepted. [S18](#s18)

For each imported release, the independently reviewed policy must name the exact full source commit,
approved workflow source digest, release version and signed manifest SHA256. The allowlist starts
empty, so unset values reject. The review snapshot above is evidence for this design; it does not
automatically become an approved image release. The acquisition layer may propose a release but
cannot add trust anchors or accepted release digests.

Because this workflow is manually dispatched and creates its release tag later, the proposed signing
identity uses main, rather than pretending the generated tag was the signing ref. Main alone is too
broad: exact commit and workflow-content approval remain mandatory. If a selected verifier cannot
enforce those bindings, it must return unsupported rather than accept weaker evidence. Pin an
established Sigstore verifier and all of its dependencies by reviewed immutable version/digest
before implementation. Do not implement signature, X.509, transparency-log or canonicalization
algorithms in project code. [S1](#s1) [S2](#s2) [S13](#s13)

Use a locally approved snapshot of Sigstore's production Fulcio and Rekor trust material. Validate
its provisioning record independently of the image bundle. Disable implicit network refresh,
alternative root discovery, environment-supplied trust overrides, insecure verification flags and
trust-on-first-use. Key rotation requires a new reviewed policy revision. The design selects this
mechanism without inventing a root hash or an untested binary version.

## Signed image contract

Define a versioned K106 manifest profile for a future release producer. Keep this as prose in the
design PR; do not add a schema or modify the producer yet. The authenticated statement must bind:

- Schema/profile version, release version and stable channel

- Repository name and numerical identity, full source commit, source ref, workflow path, full
  workflow revision, dispatch event, run ID and run attempt

- Compressed asset basename, media type, byte length and SHA256

- Expanded raw-image byte length, SHA256, logical sector size and target image family

- Compression profile, explicitly a single XZ stream with no trailing data

- Build options that affect image content, build timestamp and an explicit provenance format

- Digests and lengths for any additional evidence whose contents influence admission

Verify the exact manifest bytes against its signature before trusting values. Reject duplicate JSON
keys, non-finite numbers, malformed UTF-8, unknown profile versions, invalid integer ranges,
duplicate asset roles and unknown security-critical fields. Basenames are labels, never paths.
Bounded parsing must happen before verification, but unauthenticated fields cannot relax limits.

After manifest authentication, hash and count the compressed bytes and compare both with the
authenticated values. Only then decompress in a bounded, unprivileged verifier with a fixed memory
limit and an expanded-byte cap. Require exactly the declared length and digest, a complete
end-of-stream, no concatenated stream and no trailing data. Compression errors or limits exceeded
return a rejection. A future file adapter must supply bytes from one stable regular-file handle and
detect changes; this first core cannot open paths.

Start with a 1 MiB manifest limit, a 4 MiB evidence-bundle limit, 256 MiB decoder memory, a 16 GiB
compressed-image cap and a 64 GiB expanded-image cap. These are conservative design defaults for
review, not measured image sizes. Enforce caller cancellation and a bounded work budget. Fixtures
use tiny payloads and exercise both just-below and just-above limits without allocating full-size
buffers. Limits may be reduced locally, never raised by package data.

The verified report records the manifest digest, both image identities, exact policy revision,
verifier build identity, authenticated signer claims, checks performed and any rejection reasons. A
locally computed raw hash without a matching signed expectation can be reported as consistency-only
and cannot produce an authenticated image result.

## Offline evidence bundle

The future release package must include the image, exact manifest bytes, a Sigstore verification
bundle for the manifest, and, for continuity with the current producer, the compressed-image
signature bundle. Each bundle must bind its own exact subject bytes. The two subjects need the same
allowed workflow/repository/source identity and run binding, but need not reuse the same short-lived
certificate or signing time.

Require certificate-chain material sufficient for the approved verifier, a trusted signing-time
proof, a Rekor entry, inclusion proof and signed checkpoint. Verify proof consistency, log
signature, subject binding and certificate validity at the authenticated signing time. An inclusion
promise alone does not meet the chosen inclusion-proof requirement. A certificate expired today may
still be valid evidence if the verified signing time was within its validity period. [S13](#s13) [S14](#s14)

Store the independently approved trust-root snapshot and policy beside the package as separate
operator inputs. Include the verifier version/digest and an import inventory with file
lengths/digests. The bundle cannot authenticate its own root. Raw exported GitHub API JSON is useful
context but is not an offline authenticated assertion of repository ownership, release immutability
or final workflow success.

A later connected acquisition stage must verify that the exact repository/workflow/run attempt
completed successfully before proposing an import. The signed build manifest is created before the
workflow ends, so it cannot itself prove final workflow success. The offline core reports that limit
explicitly. If final-success proof becomes mandatory, require a separately authenticated
finalization statement and review its producer; do not infer success from a run ID or log text.

Current .sig and .pem sidecars alone do not satisfy this proposed bundle contract. They must produce
a clear incomplete-evidence rejection, with no online recovery or downgrade inside the verifier. All
bundle validation is offline. Official guidance also notes that an offline trust snapshot cannot
reveal later key revocation. [S15](#s15)

## Pure planner contract

The artifact verifier accepts bounded bytes, policy and evaluation time. The planner accepts a
successful verification result, an immutable synthetic inventory, an explicit requested target
record and synthetic freshness/confirmation context. Neither component accepts paths to read,
discovery callbacks, arbitrary executables or commands to run.

Model each device observation with a snapshot ID, host-profile ID, observation sequence and
monotonic capture time. The whole-card record includes a synthetic opaque device ID, medium CID,
controller/slot topology, kernel-device tuple, whole-device type, bus, removability, capacity,
logical sector size, read-only state and all partition/holder relationships. Capture the root, boot,
EFI, swap and mount relationships over the complete inventory graph. Unknown must remain distinct
from false.

The initial profile admits only one unambiguous whole microSD card with a unique CID and complete
native SD/MMC topology. Every target ancestor, descendant and holder must be known and disjoint from
root/boot/EFI, mounted filesystems, active swap, LVM, RAID and encrypted mappings. Reject incomplete
or inconsistent graphs, cycles, partitions, missing/duplicate IDs, unsupported buses, read-only
media, non-removable media, symlink aliases and unmatched requested targets. A bridge serial or
filesystem UUID does not substitute for the card CID.

Require target capacity to be at least the signed expanded image length. Require positive, bounded,
sector-aligned sizes and a supported sector size. Compressed size, user-provided --bytes and a
manufacturer capacity label cannot satisfy this check. A blank mount list accompanied by incomplete
collection must reject.

The planner may rank eligible candidates for display. It must not automatically select one, even
when only one candidate remains. The user must choose the record and later confirm the physical
target. A device path is a display hint only; it cannot override an absent or rejected record. There
is no unsafe-force, assume-yes, keep-mounted or custom-path escape hatch in this contract.

Return either rejected with structured reasons or candidate_for_review with a digest of all bound
inputs. Always set executable to false. The result contains no write command and no capability
token. A synthetic report must prominently identify itself as synthetic; it cannot be reused as
live-target evidence.

## Staleness and human confirmation

The future operator view must show the image release and full manifest digest, raw length, physical
medium identity, slot/location, capacity, affected partitions and a plain statement that the whole
medium will be erased. Confirmation binds the exact package, policy, inventory generation and
selected medium. A generic yes, an old approval or a ranking score is insufficient.

For the first profile, propose a maximum 30-second interval between a fresh inventory snapshot and
confirmation. Any hotplug, topology, mount, swap, holder, path mapping, identity, capacity,
protection, policy or package change invalidates the plan immediately. Elapsed time never rescues an
uncertain observation. A monotonic clock regression, missing observation or process restart also
invalidates it.

A future writer must gather a new live snapshot and repeat target checks immediately before opening
and again against the opened handle. It must bind that handle to the confirmed whole medium and
retain it for writing and readback. If identity cannot be re-established, close safely and stop
before any write. The 30-second limit is an additional expiry, not a substitute for these checks.

The current slice models those transitions using fabricated timestamps and inventory generations. It
cannot claim that this prevents a real hardware race. Live-device admission, exclusive-access
behavior and handle stability require separately reviewed platform adapters and physical-media
tests.

## Resume replay and rollback

Do not support resuming partial device writes in the first implementation. After interruption, the
plan is invalid and the medium is considered indeterminate. A later operator phase may offer a fresh
full erase/write only after the same artifact and target checks and a new explicit confirmation.

A saved plan is a historical report, not reusable authority. Re-evaluating the same inputs offline
is allowed, but produces no write permission. Confirmation records are single-session and
single-use; a reboot, process restart or inventory generation change invalidates them. This core
neither stores nor consumes live confirmations.

A valid old signature does not establish that an image is current. Require a reviewed acceptance
entry naming the exact manifest digest. Propose a 30-day maximum age for the independently imported
trust-policy snapshot and an explicit evaluation clock. Missing time, clock rollback, a future
policy timestamp or expired policy blocks candidate planning. Historical cryptographic verification
may still report a valid signature together with policy_stale.

Require a per-image-family approved release sequence or explicit digest allowlist in policy. Do not
derive rollback ordering from the generated date tag or Git SHA. A future acquisition/operation
layer must maintain and protect a highest-accepted sequence; this pure core receives that state as
input and cannot defend against its deletion by a compromised host. A request for an older release
requires a separate one-time approval bound to old and new digests and the reason. This design does
not issue that approval or lower a stored floor.

Operational recovery means restoring a separately backed-up and verified prior image under a new
operator decision. It is not an automatic consequence of failed verification. No automatic rollback,
retry-to-another-device or fallback-to-another-release is permitted.

## Synthetic acceptance cases

All cases below are specifications for a later approved implementation. None was executed for this
design. Test fixtures must contain synthetic identities and small inert byte payloads. No production
credentials, host telemetry, actual device records or downloaded OS images belong in fixtures.

- Valid test-root signed package, exact policy and complete synthetic target return
  candidate_for_review, executable false, and the expected report digest.

- Unsigned package, attacker-replaced image plus matching checksum, wrong
  issuer/identity/workflow/repository/commit/ref/channel, fork claims and missing authenticated
  claims reject.

- Tampered manifest, wrong compressed or expanded hash/length, duplicate fields, unknown version,
  overflow, oversized metadata and mixed evidence subjects reject.

- Missing certificate chain, missing or inconsistent inclusion proof/checkpoint, bad signing-time
  evidence, untrusted root and certificate invalid at signing time reject.

- Correct historical signature with expired policy reports historical authenticity but blocks
  candidate planning; clock reversal and missing time reject.

- Truncated XZ, extra stream, trailing bytes, decoder-memory limit and expansion cap reject before
  any target effect.

- Missing or duplicate CID, path-only selection, bridge-only identity, symlink alias, partition
  target, unsupported host/media and malformed topology reject.

- Root/boot/EFI ancestor or descendant, mounted filesystem, active swap, LVM/RAID/encryption holder,
  unknown mount state and undersized or misaligned capacity reject.

- Hotplug replacement at the same path, changed slot, capacity or CID, fresh mount, stale snapshot,
  reordered inventory, expired confirmation and process restart invalidate the candidate.

- A single eligible device still requires explicit selection; ranking ties and an empty set never
  select a target.

- Saved reports, old confirmation records and incomplete-write checkpoints never restore permission.
  An older release without the exact rollback decision blocks.

- Malicious labels containing paths, shell syntax, terminal escapes, newlines or credential-looking
  text remain inert and safely rendered.

- A test harness makes any socket, subprocess, environment-based trust lookup, OS device discovery,
  /dev or /sys access, mount, write, eject or telemetry call fail immediately. Both success and
  failure paths must show zero such effects.

Use two distinct test layers: deterministic policy/planner tests with an explicitly fake verifier
result, and independent offline signature-verification tests using a test-only root and
valid/invalid signed fixtures. A fake verifier returning true is never evidence that publisher
authentication works. Record fixture provenance and producer/tool version. Static test signing
material must have no production authority.

Reuse the existing test styles as references, not as permission to invoke the current installer or
flasher. Existing Linux identifier tests use temporary fake trees and monkeypatched command output,
which suits the synthetic approach. The present ordinary-file flashing tests establish existing
behavior only; they do not prove the new contract. [S9](#s9) [S10](#s10)

## Acquisition and physical operation remain separate

A later acquisition adapter may fetch an explicitly selected stable release into an unprivileged
staging area. It must bind repository, release ID/tag, run ID/attempt and exact subject digests, use
constrained HTTPS origins/redirects, and authenticate imported evidence before admitting bytes. It
may not execute the downloaded content, select mutable-main helpers, install GitHub CLI or Cosign,
run shell hooks, fall back to workflow artifacts, or treat a locally supplied helper as trusted by
default.

The first offline slice has no downloader or file adapter. It also excludes cloud-init mutation, SSD
cloning, existing-node migration, telemetry, firewall or namespace policy, credentials, host
settings and build-system hardening. Those concerns retain their own review boundaries.

A physical-media phase requires separate authorization naming the host, sacrificial medium, erasure
consequence, exact release, operator and recovery method. The human must verify the physical card,
authorize discovery, unmounting and any destructive write, and perform the final flashing action
under the applicable handoff rules. Establish backups and boot recovery before writing. Verify raw
bytes on the same bound handle and qualify actual boot behavior afterward. No design approval or
passing synthetic fixture grants this authority.

## Documentation provenance

Repository agent instructions, the Docs workflow and check tooling describe the documentation
validation process. [S6](#s6) [S7](#s7) [S8](#s8) The Test Suite and CI workflows provide broader
validation context; citing them does not claim they were run for this design. [S11](#s11) [S12](#s12)
The documentation index, ARM64 build design and repository metadata provide project context.
[S16](#s16)

## Sources

All repository citations below use the reviewed main commit
`2587b93ab1843a67beb6f2a553b9d159be8f3767`. External sources are separate from that pinned snapshot.

<a id="s1"></a>

[S1] [Release signing and
publication](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/.github/workflows/pi-image-release.yml#L197-L258)
and [release replacement
settings](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/.github/workflows/pi-image-release.yml#L298-L322).

<a id="s2"></a>

[S2] [Manifest identity
fields](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/scripts/generate_release_manifest.py#L133-L181),
[version
generation](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/scripts/generate_release_manifest.py#L42-L51)
and [workflow run
inputs](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/scripts/generate_release_manifest.py#L286-L315).

<a id="s3"></a>

[S3] [Checksum
verification](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/scripts/download_pi_image.sh#L279-L301)
and [workflow
fallback](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/scripts/download_pi_image.sh#L407-L471).

<a id="s4"></a>

[S4] [Target
discovery](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/scripts/flash_pi_media.py#L149-L258),
[root warning and device
open](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/scripts/flash_pi_media.py#L654-L713),
and [selection and write
flow](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/scripts/flash_pi_media.py#L883-L976).

<a id="s5"></a>

[S5] [Bootstrap and local
hook](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/scripts/install_sugarkube_image.sh#L117-L219),
[mutable helper
execution](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/scripts/install_sugarkube_image.sh#L462-L518),
and [local expanded
checksum](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/scripts/install_sugarkube_image.sh#L541-L557).

<a id="s6"></a>

[S6] [Repository agent
instructions](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/AGENTS.md).

<a id="s7"></a>

[S7] [Docs
workflow](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/.github/workflows/docs.yml)
and [spellcheck
configuration](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/.spellcheck.yaml).

<a id="s8"></a>

[S8] [Checks
options](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/scripts/checks.sh#L66-L75),
[docs dependency
guard](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/scripts/checks.sh#L490-L520),
[spell and local-link
checks](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/scripts/checks.sh#L632-L678)
and [pre-commit
configuration](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/.pre-commit-config.yaml).

<a id="s9"></a>

[S9] [Synthetic Linux identifier
tests](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/tests/flash_pi_media_linux_test.py).

<a id="s10"></a>

[S10] [Existing flash
tests](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/tests/flash_pi_media_test.py),
[download
tests](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/tests/download_pi_image_test.py),
[installer
tests](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/tests/install_sugarkube_image_test.py),
and [manifest
tests](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/tests/test_generate_release_manifest.py).

<a id="s11"></a>

[S11] [Test Suite
workflow](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/.github/workflows/tests.yml).

<a id="s12"></a>

[S12] [CI
workflow](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/.github/workflows/ci.yml).

<a id="s13"></a>

[S13] [Sigstore verification guidance](https://docs.sigstore.dev/cosign/verifying/verify/) and
[GitHub Actions OIDC context](https://docs.github.com/en/actions/concepts/security/openid-connect).

<a id="s14"></a>

[S14] [Sigstore bundle format](https://docs.sigstore.dev/about/bundle/).

<a id="s15"></a>

[S15] [GitHub offline attestation verification and trust-root
limits](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline).
This is general offline-trust guidance, not a claim that this repository currently generates GitHub
artifact attestations.

<a id="s16"></a>

[S16] [Documentation
index](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/docs/index.md#L14-L35),
[ARM64 build
design](https://github.com/futuroptimist/sugarkube/blob/2587b93ab1843a67beb6f2a553b9d159be8f3767/docs/pi_image_builder_design.md#L15-L43),
and [repository identity](https://api.github.com/repos/futuroptimist/sugarkube).

<a id="s17"></a>

[S17] [Linux SD and MMC block-device
attributes](https://kernel.org/doc/html/v5.7/driver-api/mmc/mmc-dev-attrs.html). This documents the
CID attribute, not qualification of a particular reader.

<a id="s18"></a>

[S18] [Fulcio GitHub Actions identity
mapping](https://docs.sigstore.dev/certificate_authority/oidc-in-fulcio/) and [Fulcio certificate
extension definitions](https://github.com/sigstore/fulcio/blob/main/docs/oid-info.md). External
documentation was consulted on 12 October 2026 and remains separate from the pinned repository
snapshot.
