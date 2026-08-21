# Infra Helpers

This directory is reserved for operational helpers such as Terraform modules,
Ansible playbooks, bootstrap helpers, and non-secret bootstrap metadata. Terraform
state and saved plans are sensitive remote artifacts and must not be committed
beneath `infra/`. Other than this README, the directory remains intentionally
empty until future platform automation is implemented in a separately reviewed change.

The documentation-only [Terraform and Ansible integration design](../docs/design/terraform-ansible-integration.md)
defines the ownership and safety boundaries that any future automation must follow.
