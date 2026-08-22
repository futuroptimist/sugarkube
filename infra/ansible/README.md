# Ansible staging validation foundation

This directory is the credential-free Ansible half of Phase B in the
[Terraform and Ansible integration design](../../docs/design/terraform-ansible-integration.md).
Ansible is reserved for carefully adopted post-boot host configuration. Terraform may own selected
external provider resources, while Helm/Just and Flux retain their existing application and
Kubernetes ownership. Every individual resource has one authoritative writer; its current writer
remains authoritative until a reviewed handoff retires that writer.

## Current scope and safety boundary

This scaffold supplies a static staging inventory, local configuration, pinned validation tools,
credential-free CI, and a future facts-based, read-only preflight. It supplies no roles, production
inventory, secrets, dynamic inventory, mutable tasks, live connection, or node convergence. In
particular, Pi imaging, bootstrap scripts, `just ha3`, `/etc/rancher/k3s/config.yaml`, Helm/Just,
Flux, and existing app workflows retain their current ownership.

The inventory contains aliases only. `sugarkube3`, `sugarkube4`, and `sugarkube5` must resolve via an
operator's existing SSH configuration when a later review authorizes live use. Host-key checking is
explicitly enabled. Before any connection, validate each fingerprint through an independent,
trusted channel; never accept an unexpected or unverified key.

Do not commit SSH keys, passwords, tokens, vault passwords, kubeconfigs, privilege-escalation
credentials, or private topology. They also must not enter inventory, cached facts, or logs. Ignore
rules are defense in depth, not permission to create secret material in this tree.

## Install and validate locally

The repository's supported Python 3.12 can install the exact validation dependencies in an isolated
environment. Run from the repository root:

```bash
python3.12 -m venv /tmp/sugarkube-ansible-validate
/tmp/sugarkube-ansible-validate/bin/python -m pip install \
  --requirement infra/ansible/requirements.txt
export PATH="/tmp/sugarkube-ansible-validate/bin:$PATH"
export ANSIBLE_CONFIG="$PWD/infra/ansible/ansible.cfg"

ansible-config dump --only-changed
ansible-inventory --inventory infra/ansible/inventories/staging/hosts.yml --graph
ansible-inventory --inventory infra/ansible/inventories/staging/hosts.yml --list
yamllint infra/ansible
ansible-lint infra/ansible/playbooks/staging_preflight.yml
ansible-playbook --inventory infra/ansible/inventories/staging/hosts.yml \
  --syntax-check infra/ansible/playbooks/staging_preflight.yml
```

The three exact pins in `requirements.txt` are intentionally reviewed together. To update them,
identify current stable releases compatible with Python 3.12, change all necessary pins, install
them together in a fresh virtual environment, and repeat every validation command above. Exact pins
keep local and CI validation reproducible; no Galaxy collection is needed because the playbook uses
only `ansible.builtin` modules.

## Future live milestones (not authorized here)

> **Warning:** The following operator command is documentation for a later, separately authorized
> live canary. This task and CI do not run it or connect to any staging node.

```bash
ansible-playbook --inventory infra/ansible/inventories/staging/hosts.yml \
  --limit sugarkube3 --check --diff infra/ansible/playbooks/staging_preflight.yml
```

The first live milestone gathers facts and performs only read-only baseline validation across
staging because reachability and durable host assumptions must be established before ownership or
configuration changes are considered. A separate PR may then introduce the first mutable role, but
it must adopt exactly one low-risk, reversible responsibility from its current writer.

That later convergence must start with a canary and proceed serially, with cluster readiness and
quorum gates before and after each node. Its review must define rollback, stop on degraded health,
and require a second run to report `changed=0`. Check mode and diff output aid review but never by
themselves authorize a live connection or mutation.
