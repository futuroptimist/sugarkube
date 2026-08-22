variable "cloudflare_zone_id" {
  type        = string
  description = "Cloudflare's 32-character hexadecimal zone identifier. It is an identifier, not a credential, but remains an uncommitted operator input."

  validation {
    condition     = can(regex("^[0-9a-fA-F]{32}$", var.cloudflare_zone_id))
    error_message = "cloudflare_zone_id must be exactly 32 hexadecimal characters."
  }
}

variable "tf_lab_txt_content" {
  type        = string
  description = "Non-secret, printable ASCII training content beginning with sugarkube-terraform-lab: and no more than one 255-octet TXT character-string."

  validation {
    condition = (
      startswith(var.tf_lab_txt_content, "sugarkube-terraform-lab:") &&
      length(var.tf_lab_txt_content) <= 255 &&
      can(regex("^[ -~]+$", var.tf_lab_txt_content))
    )
    error_message = "tf_lab_txt_content must begin with sugarkube-terraform-lab:, contain only printable ASCII, and be at most 255 characters."
  }
}
