output "tf_lab_fqdn" {
  description = "FQDN of the disposable Terraform training record."
  value       = cloudflare_dns_record.tf_lab.name
}
