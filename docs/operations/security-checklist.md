---
personas:
  - software
---

# Sugarkube Operations Security Checklist

Use this checklist when rotating credentials, auditing access, or closing out Tutorial 13's
"Optimise and secure the expanded cluster" milestone. Copy the template into your lab evidence
repository (for example, `~/sugarkube-labs/tutorial-13/operations/security-checklist.md`) so every
rotation leaves an auditable trail you can reference during incident reviews or future proposals.

## How to Use This Checklist
- Print or copy this file before starting a maintenance window.
- Record the date, operators involved, and the target nodes in the evidence log below.
- Mark each checkbox as you complete the tasks. Capture command output in your lab repo or support
  bundle archives.
- When running in production, coordinate changes in the team's Slack channel and link the run log
  from the relevant pull request or outage ticket.

## Rotation Checklist
- [ ] Announce the rotation window and confirm observers are monitoring `kubectl get events -A`.
- [ ] Generate fresh host keys and admin key pairs:
  ```bash
  sudo ssh-keygen -A
  ssh-keygen -t ed25519 -f ~/.ssh/sugarkube-admin-$(date +%Y%m%d) -C "sugarkube admin"
  ```
- [ ] Replace stale `authorized_keys` entries and remove any unused local accounts.
- [ ] Capture fingerprints for the new host keys and publish them in the run log:
  ```bash
  sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
  ```
- [ ] Restart SSHD and confirm the unit is healthy: `sudo systemctl restart ssh && sudo systemctl
  status ssh`.
- [ ] Update downstream automation secrets (for example, GitHub deploy keys, CI runners, or
  Cloudflare tunnels) with the refreshed credentials.

## Verification Checklist
- [ ] Connect with `ssh -o StrictHostKeyChecking=yes` from a clean workstation to validate the new
  fingerprint.
- [ ] Run `kubectl get nodes -o wide` and `kubectl top nodes` to confirm cluster health after the
  rotation.
- [ ] Review `sudo journalctl -u ssh --since "-15 minutes"` for authentication failures or restart
  loops.
- [ ] Spot-check `projects-compose.service` and other long-running workloads:
  `sudo systemctl status projects-compose.service`.
- [ ] Trigger a short `fio` read test (matching Tutorial 13) to ensure storage throughput remains in
  the expected range.

## Evidence Log
Document every rotation so future audits and proposals can trace the changes.

| Date | Host | Fingerprint | Method | Notes |
| --- | --- | --- | --- | --- |
| YYYY-MM-DD | pi-controller | SHA256:examplefingerprint | ssh-keygen -lf | Rotated during Tutorial 13 |

| Date | Activity | Impact | Follow-up |
| --- | --- | --- | --- |
| YYYY-MM-DD | Restarted sshd | No downtime | Schedule quarterly rotation reminders |

## References
- [Pi Support Bundles](../pi_support_bundles.md) — capture evidence before and after rotations.
- [projects-compose.md](../projects-compose.md) — verify compose workloads after credential updates.
- [pi_multi_node_join_rehearsal.md](../pi_multi_node_join_rehearsal.md) — rehearse recovery joins with
  the new tokens.
