# Infra Helpers

This directory is reserved for operational helpers such as Terraform modules,
Ansible playbooks, bootstrap helpers, and non-secret bootstrap metadata. The
[credential-free Terraform validation foundation](terraform/README.md) is the first
implementation beneath `infra/`; it manages no resources. Terraform state and saved
plans are sensitive remote artifacts and must not be committed beneath `infra/`.

The [Terraform and Ansible integration design](../docs/design/terraform-ansible-integration.md)
defines the ownership and safety boundaries that this scaffold and any future
automation must follow.
