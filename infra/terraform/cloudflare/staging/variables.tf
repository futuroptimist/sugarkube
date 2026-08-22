variable "cloudflare_zone_id" {
  type        = string
  description = "Cloudflare zone identifier supplied by the operator. A zone ID is an identifier, not a credential, but remains an uncommitted runtime input."

  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.cloudflare_zone_id))
    error_message = "cloudflare_zone_id must be exactly 32 lowercase hexadecimal characters."
  }
}

variable "tf_lab_txt_content" {
  type        = string
  description = "Non-secret disposable lab content, beginning with the recognizable training prefix."

  validation {
    condition = (
      startswith(var.tf_lab_txt_content, "sugarkube-terraform-lab:") &&
      length(var.tf_lab_txt_content) > length("sugarkube-terraform-lab:") &&
      length(var.tf_lab_txt_content) <= 255
    )
    error_message = "tf_lab_txt_content must start with sugarkube-terraform-lab:, include content after the prefix, and contain at most 255 characters."
  }
}
