output "tf_lab_fqdn" {
  description = "The non-sensitive fully qualified name of the disposable training record."
  value       = cloudflare_dns_record.tf_lab.name
}
