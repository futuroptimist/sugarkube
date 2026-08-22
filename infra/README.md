# Infra Helpers

This directory is reserved for operational helpers such as Terraform roots,
Ansible playbooks, bootstrap helpers, and non-secret bootstrap metadata. The
[credential-free Terraform foundation](terraform/README.md) provides validation-only
scaffolding; it manages no resources. Terraform state and saved plans are sensitive
artifacts and must not be committed beneath `infra/`.

The [Terraform and Ansible integration design](../docs/design/terraform-ansible-integration.md)
defines the ownership and safety boundaries that any future automation must follow.
