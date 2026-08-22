terraform {
  required_version = "= 1.15.9"

  # HCP Terraform organization and workspace are supplied at runtime.
  cloud {}

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.23.0"
    }
  }
}
