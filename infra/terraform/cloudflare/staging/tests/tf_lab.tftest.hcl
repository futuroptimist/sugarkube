mock_provider "cloudflare" {}

variables {
  cloudflare_zone_id = "0123456789abcdef0123456789abcdef"
  tf_lab_txt_content = "sugarkube-terraform-lab:mock-test-only"
}

run "tf_lab_contract" {
  command = plan

  assert {
    condition     = cloudflare_dns_record.tf_lab.name == "tf-lab.gitshelves.com"
    error_message = "The lab must use only the intended FQDN."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.type == "TXT"
    error_message = "The lab record must be TXT."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.content == var.tf_lab_txt_content
    error_message = "The configured lab content must pass through unchanged."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.ttl == 300
    error_message = "The lab TTL must be 300 seconds."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.proxied == false
    error_message = "The TXT record must not be proxied."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.comment == "Disposable Sugarkube Terraform training record"
    error_message = "The comment must identify the disposable training purpose."
  }

  assert {
    condition     = output.tf_lab_fqdn == "tf-lab.gitshelves.com"
    error_message = "The only output must expose the lab FQDN."
  }
}

run "reject_invalid_zone_id" {
  command = plan

  variables {
    cloudflare_zone_id = "not-a-zone-id"
  }

  expect_failures = [var.cloudflare_zone_id]
}

run "reject_invalid_txt_prefix" {
  command = plan

  variables {
    tf_lab_txt_content = "unrecognizable-content"
  }

  expect_failures = [var.tf_lab_txt_content]
}

run "reject_oversized_txt_content" {
  command = plan

  variables {
    tf_lab_txt_content = "sugarkube-terraform-lab:${join("", [for index in range(233) : "x"])}"
  }

  expect_failures = [var.tf_lab_txt_content]
}
