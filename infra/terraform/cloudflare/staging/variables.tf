variable "cloudflare_zone_id" {
  description = "Cloudflare zone identifier supplied by the operator at runtime. Zone IDs are identifiers, not credentials, but remain uncommitted operator inputs."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.cloudflare_zone_id))
    error_message = "cloudflare_zone_id must be a 32-character lowercase hexadecimal Cloudflare zone identifier."
  }
}

variable "tf_lab_txt_content" {
  description = "Non-secret, disposable lab text supplied by the operator at runtime."
  type        = string

  validation {
    condition     = startswith(var.tf_lab_txt_content, "sugarkube-terraform-lab:")
    error_message = "tf_lab_txt_content must start with sugarkube-terraform-lab:."
  }

  validation {
    condition     = length(var.tf_lab_txt_content) <= 255
    error_message = "tf_lab_txt_content must be no longer than 255 characters."
  }

  validation {
    condition     = can(regex("^[ -~]+$", var.tf_lab_txt_content))
    error_message = "tf_lab_txt_content must contain only printable ASCII characters."
  }
}
