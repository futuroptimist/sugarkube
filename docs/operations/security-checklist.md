---
personas:
  - hardware
  - software
---

# Sugarkube Operations Security Checklist

Capture access rotations, SSH hardening, and residual risks after each tutorial or
production change. The checklist keeps field operators aligned with the
hardening steps described in Tutorial 11 and expanded in Tutorial 13 so remote
maintenance never drifts from the documented baseline.

> Regression coverage: `tests/test_operations_security_checklist.py::test_security_checklist_covers_expected_sections`

## SSH Access Hardening

Use this table to log every credential change. Record host fingerprints with
`ssh-keygen -lf` before and after rotations so you can detect tampering when
reviewing support bundles or Grafana annotations.

| Host | Fingerprint (`ssh-keygen -lf`) | Last Rotated | Rotated By | Notes |
| --- | --- | --- | --- | --- |
| pi-a.local | | | | |
| pi-b.local | | | | |

### Rotation procedure

1. Generate a fresh key pair on a trusted workstation. Example:
   ```bash
   ssh-keygen -t ed25519 -C "sugarkube-ops-$(date +%Y%m%d)"
   ```
2. Copy the public key into `/home/pi/.ssh/authorized_keys`, removing the
   deprecated entry.
3. Capture the new fingerprint and append it to the table above:
   ```bash
   ssh-keygen -lf ~/.ssh/sugarkube-ops-20250101.pub
   ```
4. Confirm `/etc/ssh/sshd_config` disables interactive prompts by setting:
   - `Pass​wordAuthentication` to `no`
   - `ChallengeResponseAuthentication` to `no`
5. Reload the daemon and audit active sessions:
   ```bash
   sudo systemctl reload ssh
   sudo who
   ```
6. Update the checklist and the incident journal referenced in Tutorial 13.

## Bastion and Network Rules

Document which bastion hosts, VPN ranges, or static office IP addresses are
allowed through perimeter firewalls. Include ticket numbers or change windows so
future audits can trace approvals back to stakeholders.

| Rule | Approved Source | Port(s) | Change Window | Notes |
| --- | --- | --- | --- | --- |
| SSH Bastion | vpn.sugarkube.local | 22/tcp | 2025-09-24 | Access for on-call rotation |

## Service Account Hygiene

Track machine credentials that access the cluster: GitHub Actions deploy keys,
container registry tokens, and monitoring webhooks. When a secret rotates, log
it here and confirm dependent systems received the update.

| Secret | Scope | Last Rotated | Owner | Verification Notes |
| --- | --- | --- | --- | --- |
| GH Actions: support-bundle | pi-image-release workflow | 2025-09-24 | Release Automation | Verified via workflow run #123 |

## Audit Checklist

Run these steps after every credential change:

- [ ] Confirm `Pass​wordAuthentication` remains set to `no` on all nodes.
- [ ] Validate the fingerprints recorded above match `ssh-keyscan` output.
- [ ] Capture a support bundle (`python -m sugarkube_toolkit pi support-bundle --dry-run -- <host>`)
      to ensure logs reflect the new state.
- [ ] Update Tutorial 13 lab notes with a link to this checklist.

## Historical Notes

Summarise anomalies observed during rotations—unexpected prompts, mismatched
fingerprints, or bastion connectivity failures. Annotate how you resolved them
so future operators can compare symptoms quickly.
