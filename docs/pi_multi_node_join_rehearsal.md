---
personas:
  - hardware
  - software
---

# Pi Multi-Node Join Rehearsal

Scaling from a single Sugarkube control-plane to a multi-node k3s cluster is smoother when you
practice the flow in advance. The `pi_multi_node_join_rehearsal.py` helper retrieves the join token
from an existing controller, prints a ready-to-run join command, and runs SSH-based preflight checks
against candidate worker nodes. Use it after your first node reaches `k3s-ready.target` to build
confidence that the token is accessible, the API endpoint is reachable, and each worker can download
`https://get.k3s.io` before you touch production hardware.

By default the script is read-only: it never starts `k3s agent` or modifies cluster state. Add
`--apply` to promote rehearsal into automation and run the join command remotely, then append
`--apply-wait` to watch until every node reports `Ready`.

## Prerequisites

- SSH key access to the control-plane node (default user: `pi`).
- `sudo` privileges on the control-plane so the script can read `/boot/sugarkube-node-token` and run
  `k3s kubectl`.
- Optional: SSH access to the worker nodes you plan to join with sudo configured for
  non-interactive execution.
- Workstation with Python 3 and `ssh` installed. The helper runs locally and shells out to SSH.

If your nodes use different usernames or key paths, override them with `--server-user`,
`--agent-user`, and `--identity`.

## Quick start

Run the rehearsal directly with `just` or `make` once your controller is online:

```bash
just rehearse-join REHEARSAL_ARGS="sugar-control.local --agents pi-a.local pi-b.local"
```

Prefer to stay inside the unified CLI? Preview the helper with:

```bash
python -m sugarkube_toolkit pi rehearse --dry-run -- sugar-control.local --agents pi-a.local pi-b.local
```

Drop `--dry-run` to run the rehearsal immediately. Everything after the standalone `--` is forwarded to
`scripts/pi_multi_node_join_rehearsal.py`, matching the behaviour described throughout this guide
(`tests/test_sugarkube_toolkit_cli.py::test_pi_rehearse_invokes_helper` guards the CLI parity).

The command:

1. Connects to `sugar-control.local` over SSH and reads `/boot/sugarkube-node-token`.
2. Runs `k3s kubectl get nodes -o json` to confirm the control-plane is `Ready`.
3. Prints a join command template you can paste onto a worker (replace `<node-name>`).
4. SSHes into each prospective worker (`pi-a.local`, `pi-b.local`) and checks:
   - The `https://get.k3s.io` installer is reachable with `curl`.
   - The worker can open a TCP socket to the controller on port `6443`.
   - Whether `k3s-agent` is already running or still inactive.
   - Whether previous registration artifacts exist (`/etc/rancher/k3s/registration.yaml`,
     `/var/lib/rancher/k3s/agent`).

Exit code is `0` when every agent passes the preflight; failures or warnings raise a non-zero exit
code so you can wire the rehearsal into automation.

Ready to go beyond rehearsal? Trigger the full join workflow with:

```bash
just cluster-up CLUSTER_ARGS="sugar-control.local --agents pi-a.local pi-b.local --apply --apply-wait"
```

The command reuses the same helper but automatically:

1. Runs the preflight checks described above.
2. Aborts if any worker fails the preflight so you never join a broken node.
3. Executes the k3s installer on each worker with a deterministic node name (defaults to the host).
4. Polls `k3s kubectl get nodes` until the control-plane plus workers report `Ready` or the
   timeout (default 5 minutes) expires.

## Join secret handling

By default, the join secret (the mirrored k3s node token) is redacted in the console output.
Re-run with `--reveal-secret` to print the full value (treat it as sensitive) or
`--save-secret /secure/path/k3s.secret` to write it locally with `chmod 600` for later use.

If the control-plane exposes the API on a different address or port, pass
`REHEARSAL_ARGS="--server-url https://10.99.0.12:7443 sugar-control.local"` so workers probe the
correct endpoint during their TCP test.

## Advanced usage

- Run without `--agents` to rehearse only the control-plane checks and join-secret retrieval.
- Use `--agent-no-sudo` when workers cannot run privileged commands; the script still verifies basic
  reachability but skips filesystem probes.
- Supply `--json` to capture machine-readable summaries for logging systems.
- Export `REHEARSAL_ARGS` in CI or home-lab automation to block deployments when a worker loses
  network access or when the mirrored join secret goes missing.

## Next steps

Once the rehearsal passes, either run the printed join command on each worker or rerun with
`--apply --apply-wait` to promote it into automation. The
[`Raspberry Pi Cluster Setup`](./raspi_cluster_setup.md#5-form-the-k3s-cluster) guide shows how to
monitor `sudo k3s kubectl get nodes --watch` if you prefer to observe manually.
