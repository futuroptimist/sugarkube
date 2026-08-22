# Ansible staging validation foundation

This directory is the credential-free Ansible half of Phase B in the
[Terraform and Ansible integration design](../../docs/design/terraform-ansible-integration.md).
Ansible is reserved for explicitly adopted post-boot host configuration. Terraform manages selected
external provider resources, while Helm/Just and Flux retain their existing application and
Kubernetes ownership. Every individual resource has exactly one authoritative writer; merely
describing a future responsibility here does not transfer ownership.

## Current scope and boundaries

The scaffold contains one static staging inventory, local configuration, pinned validation tools,
and a facts-based, read-only preflight playbook. It creates no production inventory, roles, host or
group variables, secrets, vaults, dynamic inventory, or mutable tasks. It neither authorizes nor
performs a host connection.

Pi imaging, bootstrap scripts, `just ha3`, `/etc/rancher/k3s/config.yaml`, Helm/Just, Flux, and
existing application workflows retain their current ownership. Ansible does not deploy applications,
write Kubernetes resources, or alter external infrastructure.

The inventory names `sugarkube3`, `sugarkube4`, and `sugarkube5` as aliases only. A future authorized
operator's existing SSH configuration must resolve those aliases. Host-key checking is explicitly
enabled. Validate each fingerprint through a trusted out-of-band channel before any first connection;
never accept an unexpected key or disable strict verification.

## Install and validate locally

Use the repository-supported Python 3.12 in an isolated environment, from the repository root:

```bash
python3.12 -m venv /tmp/sugarkube-ansible-validate
/tmp/sugarkube-ansible-validate/bin/python -m pip install \
  --requirement infra/ansible/requirements.txt
export PATH="/tmp/sugarkube-ansible-validate/bin:$PATH"
export ANSIBLE_CONFIG="$PWD/infra/ansible/ansible.cfg"

ansible-config dump --only-changed
ansible-inventory --graph
ansible-inventory --inventory infra/ansible/inventories/staging/hosts.yml --list
yamllint infra/ansible
ansible-lint infra/ansible/playbooks/staging_preflight.yml
ansible-playbook --inventory infra/ansible/inventories/staging/hosts.yml \
  --syntax-check infra/ansible/playbooks/staging_preflight.yml
```

Ansible resolves the relative inventory and roles paths in `ansible.cfg` from the configuration
file's directory. Consequently, `ansible-inventory --graph` uses the checked-in staging inventory
when the command is run from the repository root with `ANSIBLE_CONFIG` set as shown above.

The exact pins in `requirements.txt` keep local and CI validation reproducible. To update them,
review the current stable `ansible-core`, `ansible-lint`, and `yamllint` releases for Python 3.12 and
mutual compatibility, change all relevant exact pins together, install them in a new environment,
and rerun every command above. No Galaxy collection is needed because the playbook uses only
`ansible.builtin` modules.

## Future live milestone (not authorized by this scaffold)

The first live milestone will gather facts and perform only read-only baseline checks across staging.
An operator may later begin with this canary command **only after separate review and authorization**:

```bash
ansible-playbook --inventory infra/ansible/inventories/staging/hosts.yml \
  --limit sugarkube3 --check --diff \
  infra/ansible/playbooks/staging_preflight.yml
```

This task and its CI do **not** execute that command. Check mode is not permission to connect to a
host. Facts and read-only assertions come first so operators can validate assumptions without taking
ownership or changing a node.

The first mutable role will be a separate PR that adopts exactly one low-risk, reversible
responsibility and retires its prior writer. That rollout must use a canary and serial execution,
cluster readiness and quorum gates before and after each step, a tested rollback, and a second
convergence run reporting `changed=0` before promotion.

## Secrets policy

Never put SSH keys, login or vault-decryption passphrases, tokens, kubeconfigs,
privilege-escalation credentials, private topology, cached facts, or secret-bearing logs in Git or
inventory. Supply any future authorized authentication through approved runtime mechanisms. Ignore
rules reduce accidental local artifact commits but are not a substitute for reviewing content and
scanning for secrets.
