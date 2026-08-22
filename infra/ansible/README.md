# Ansible staging validation foundation

This directory is the credential-free Ansible half of Phase B in the
[Terraform and Ansible integration design](../../docs/design/terraform-ansible-integration.md).
Ansible is intended for explicitly adopted post-boot host configuration. Terraform owns only
separately adopted external provider resources, while Helm/Just and Flux retain their existing
application and Kubernetes ownership. **Every individual resource has one authoritative writer.**
An Ansible role may take responsibility only after a reviewed handoff retires the previous writer.

## Current scope and safety boundary

This scaffold provides a static staging inventory, safe local configuration, pinned validation
tools, a read-only future preflight, and static CI. It has no production inventory, roles, host or
group variables, secrets, vault, dynamic inventory, persistent fact cache, repository log, or
mutable playbook. Validation does not contact a host.

The aliases `sugarkube3`, `sugarkube4`, and `sugarkube5` contain no connection data. During a later,
separately authorized live run, the operator's existing SSH configuration must resolve them. Ansible
keeps strict SSH host-key checking enabled. Validate every host fingerprint out of band before a
first connection; never accept a changed or unknown key merely to continue.

Pi imaging and bootstrap scripts retain their current ownership, as do `just ha3`,
`/etc/rancher/k3s/config.yaml`, Helm/Just, Flux, and existing application workflows. This scaffold
does not install packages, configure nodes or k3s, deploy applications, or mutate infrastructure.

## Install and validate locally

Use the repository-supported Python 3.12 in an isolated environment, from the repository root:

```bash
python3.12 -m venv /tmp/sugarkube-ansible-validate
/tmp/sugarkube-ansible-validate/bin/python -m pip install \
  --requirement infra/ansible/requirements.txt
export PATH="/tmp/sugarkube-ansible-validate/bin:$PATH"
export ANSIBLE_CONFIG="$PWD/infra/ansible/ansible.cfg"
```

Inspect and statically validate the checked-in content without connecting to a node:

```bash
ansible-config dump --only-changed
ansible-inventory --inventory infra/ansible/inventories/staging/hosts.yml --graph
ansible-inventory --inventory infra/ansible/inventories/staging/hosts.yml --list
yamllint infra/ansible
ansible-lint infra/ansible/playbooks/staging_preflight.yml
ansible-playbook \
  --inventory infra/ansible/inventories/staging/hosts.yml \
  --syntax-check infra/ansible/playbooks/staging_preflight.yml
```

`requirements.txt` pins exact, mutually compatible releases so local and CI validation agree. To
update them, review the current stable releases and Python requirements for all three packages,
change all affected pins together, install them in a fresh Python 3.12 environment, review transitive
dependency resolution, and rerun every command above before committing.

## Future operator milestone — not authorized here

The first live milestone will gather facts and run this read-only baseline across staging. That
limited step establishes reachability and platform evidence before Ansible owns any node setting.
The following future canary command is documentation only: **this task and its CI do not authorize or
execute it.**

```bash
ansible-playbook \
  --inventory infra/ansible/inventories/staging/hosts.yml \
  --limit sugarkube3 \
  --check \
  --diff \
  infra/ansible/playbooks/staging_preflight.yml
```

The first mutable role must be a separate PR adopting exactly one low-risk, reversible
responsibility from its current writer. Its rollout must use a canary and serial execution, enforce
cluster readiness and quorum gates before and after each node, document rollback, and require a
second convergence run with `changed=0` before promotion.

## Secrets policy

Never put SSH keys, passwords, tokens, vault passwords, kubeconfigs, privilege-escalation
credentials, or private topology in Git, inventory, cached facts, or logs. Ignore rules are only a
backstop for local artifacts, not a secret-storage mechanism. Supply any credentials for a future
authorized operation through an approved runtime mechanism and keep their values out of output.
