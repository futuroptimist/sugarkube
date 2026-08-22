resource "cloudflare_dns_record" "tf_lab" {
  zone_id = var.cloudflare_zone_id
  name    = "tf-lab.gitshelves.com"
  type    = "TXT"
  content = var.tf_lab_txt_content
  ttl     = 300
  proxied = false
  comment = "Disposable Sugarkube Terraform training record"
}

output "tf_lab_fqdn" {
  description = "The non-sensitive fully qualified name of the disposable training record."
  value       = cloudflare_dns_record.tf_lab.name
}
