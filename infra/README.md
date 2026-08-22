# Infra Helpers

This directory contains the credential-free [Terraform validation foundation](terraform/README.md)
and [Ansible staging validation foundation](ansible/README.md). It is reserved for operational
helpers such as future Terraform modules, Ansible playbooks, bootstrap helpers, and non-secret
bootstrap metadata. Terraform state and saved plans are sensitive remote artifacts and must not be
committed beneath `infra/`.

The [Terraform and Ansible integration design](../docs/design/terraform-ansible-integration.md)
defines the ownership and safety boundaries that this foundation and any future automation must
follow.
