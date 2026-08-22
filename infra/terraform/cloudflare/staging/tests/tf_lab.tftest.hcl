mock_provider "cloudflare" {}

variables {
  cloudflare_zone_id = "0123456789abcdef0123456789abcdef"
  tf_lab_txt_content = "sugarkube-terraform-lab:mock-test-only"
}

run "plans_only_the_disposable_txt_record" {
  command = plan

  assert {
    condition     = cloudflare_dns_record.tf_lab.name == "tf-lab.gitshelves.com"
    error_message = "cloudflare_dns_record.tf_lab must use the lab FQDN."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.type == "TXT"
    error_message = "cloudflare_dns_record.tf_lab must be a TXT record."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.content == var.tf_lab_txt_content
    error_message = "cloudflare_dns_record.tf_lab must pass through the supplied content."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.ttl == 300
    error_message = "cloudflare_dns_record.tf_lab must use the documented 300-second TTL."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.proxied == false
    error_message = "cloudflare_dns_record.tf_lab must not be proxied."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.comment == "Disposable Sugarkube Terraform training record"
    error_message = "cloudflare_dns_record.tf_lab must identify its disposable training purpose."
  }

  assert {
    condition     = output.tf_lab_fqdn == "tf-lab.gitshelves.com"
    error_message = "The only output must expose the lab FQDN."
  }
}

run "rejects_invalid_zone_id" {
  command = plan

  variables {
    cloudflare_zone_id = "not-a-zone-id"
  }

  expect_failures = [var.cloudflare_zone_id]
}

run "rejects_invalid_txt_content" {
  command = plan

  variables {
    tf_lab_txt_content = "unrecognized-content"
  }

  expect_failures = [var.tf_lab_txt_content]
}

run "rejects_oversized_txt_content" {
  command = plan

  variables {
    tf_lab_txt_content = "sugarkube-terraform-lab:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  }

  expect_failures = [var.tf_lab_txt_content]
}
