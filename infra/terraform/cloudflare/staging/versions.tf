terraform {
  required_version = "= 1.15.9"

  # Organization and workspace are selected at runtime with
  # TF_CLOUD_ORGANIZATION and TF_WORKSPACE.
  cloud {}

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.23.0"
    }
  }
}
