output "tf_lab_fqdn" {
  description = "Non-sensitive fully qualified domain name of the disposable lab record."
  value       = cloudflare_dns_record.tf_lab.name
}
