variable "cloudflare_zone_id" {
  description = "Cloudflare zone identifier supplied by the operator at runtime. Zone IDs are identifiers, not credentials, but remain uncommitted operator inputs."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.cloudflare_zone_id))
    error_message = "cloudflare_zone_id must be exactly 32 lowercase hexadecimal characters."
  }
}

variable "tf_lab_txt_content" {
  description = "Non-secret disposable lab content, supplied by the operator at runtime."
  type        = string

  validation {
    condition = (
      startswith(var.tf_lab_txt_content, "sugarkube-terraform-lab:") &&
      length(var.tf_lab_txt_content) <= 255
    )
    error_message = "tf_lab_txt_content must start with sugarkube-terraform-lab: and contain at most 255 characters."
  }
}
