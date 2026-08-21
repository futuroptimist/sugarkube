# Infra Helpers

This directory is reserved for operational helpers such as Terraform modules,
Ansible playbooks, bootstrap helpers, and non-secret bootstrap metadata. Terraform
state and saved plans are sensitive remote artifacts and must not be committed
beneath `infra/`. It is intentionally empty in this commit to reserve structure
for future platform automation.

The documentation-only [Terraform and Ansible integration design](../docs/design/terraform-ansible-integration.md)
defines the ownership and safety boundaries that any future automation must follow.
