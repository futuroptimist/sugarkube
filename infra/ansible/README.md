# Ansible staging validation foundation

This directory is the credential-free Ansible half of Phase B in the
[Terraform and Ansible integration design](../../docs/design/terraform-ansible-integration.md).
Ansible's future boundary is post-boot host configuration. Terraform owns only separately adopted
external provider resources, while Helm/Just and Flux retain their existing application and
Kubernetes ownership. Every individual resource has exactly one authoritative writer: Ansible may
adopt a responsibility only through a separately reviewed handoff that retires its previous writer.

## Current scope and safety boundary

This scaffold provides a static three-host staging inventory, strict configuration, pinned validation
tools, credential-free CI, and a future facts-based read-only preflight. It provides no production
inventory, roles, variables, secrets, dynamic inventory, persistent fact cache, logs, or mutable
playbook. Neither this task nor CI authorizes a host connection or live playbook run.

The aliases `sugarkube3`, `sugarkube4`, and `sugarkube5` contain no topology or connection settings.
During a separately authorized future run, the operator's existing SSH configuration must resolve
them. Host-key checking remains enabled; validate every fingerprint out of band before connecting.
Never bypass host-key or certificate verification.

Pi imaging and bootstrap scripts remain authoritative for the base image and bootstrap. Existing
`just ha3` procedures and `/etc/rancher/k3s/config.yaml` ownership remain unchanged. Helm/Just, Flux,
and existing application workflows continue to own their current Kubernetes and application
resources.

## Install and validate locally

The repository supports Python `3.x`. Install only the exact validation dependencies in an isolated
environment, then point Ansible explicitly at the checked-in configuration:

```bash
python3 -m venv /tmp/sugarkube-ansible-validate
/tmp/sugarkube-ansible-validate/bin/python -m pip install \
  --requirement infra/ansible/requirements.txt
export PATH="/tmp/sugarkube-ansible-validate/bin:$PATH"
export ANSIBLE_CONFIG="$PWD/infra/ansible/ansible.cfg"
```

Inspect the inventory and configuration, lint the files, and perform syntax validation only:

```bash
ansible-config dump --only-changed
ansible-inventory --inventory infra/ansible/inventories/staging/hosts.yml --graph
ansible-inventory --inventory infra/ansible/inventories/staging/hosts.yml --list
yamllint infra/ansible
ansible-lint infra/ansible/playbooks/staging_preflight.yml
ansible-playbook --inventory infra/ansible/inventories/staging/hosts.yml \
  --syntax-check infra/ansible/playbooks/staging_preflight.yml
```

`requirements.txt` pins mutually tested releases so CI and operators validate with the same tools.
To update them, review the current stable releases and their supported Python/Ansible ranges, change
all affected exact pins together, install them in a fresh virtual environment, and rerun every command
above. Review dependency release notes rather than updating a single package in isolation.

## Future live milestones (not authorized here)

The first live milestone is fact gathering and this read-only Linux/ARM64 preflight across staging.
That establishes reachability and a known baseline without claiming ownership or changing nodes. A
future operator may eventually use this canary command, but **this task does not authorize or execute
it**:

```bash
ansible-playbook --inventory infra/ansible/inventories/staging/hosts.yml \
  --limit sugarkube3 --check --diff infra/ansible/playbooks/staging_preflight.yml
```

After all staging nodes pass a separately authorized read-only milestone, the first mutable role must
arrive in another PR and adopt exactly one low-risk, reversible responsibility. Mutable work must use
a canary and then serial execution, enforce cluster-readiness gates before and after each node, and
stop on degraded readiness. Its reviewed rollback must restore the previous known-good state, and a
second convergence run must report `changed=0` before promotion.

Secrets do not belong in Git, inventory, cached facts, or logs. Never store SSH keys, passwords,
tokens, vault passwords, kubeconfigs, or privilege-escalation credentials here. Supply any future
approved authentication at runtime through the established operator mechanism; ignore rules are only
defense in depth and are not a secret-storage policy.
