mock_provider "cloudflare" {}

variables {
  cloudflare_zone_id = "0123456789abcdef0123456789abcdef"
  tf_lab_txt_content = "sugarkube-terraform-lab:mock-test-only"
}

run "tf_lab_contract" {
  command = plan

  assert {
    condition     = cloudflare_dns_record.tf_lab.name == "tf-lab.gitshelves.com"
    error_message = "The lab must manage only the designated FQDN."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.type == "TXT"
    error_message = "The lab record must be TXT."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.content == var.tf_lab_txt_content
    error_message = "The resource must pass through the tested TXT content."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.ttl == 300
    error_message = "The disposable lab TTL must be 300 seconds."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.proxied == false
    error_message = "TXT records in this lab must not be proxied."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.comment == "Disposable Sugarkube Terraform training record"
    error_message = "The record comment must identify its disposable training purpose."
  }

  assert {
    condition     = output.tf_lab_fqdn == "tf-lab.gitshelves.com"
    error_message = "The sole public output must expose the lab FQDN."
  }
}

run "reject_invalid_zone_id" {
  command = plan

  variables {
    cloudflare_zone_id = "not-a-zone-id"
  }

  expect_failures = [var.cloudflare_zone_id]
}

run "reject_invalid_txt_content" {
  command = plan

  variables {
    tf_lab_txt_content = "not-the-lab-prefix"
  }

  expect_failures = [var.tf_lab_txt_content]
}

run "reject_oversized_txt_content" {
  command = plan

  variables {
    tf_lab_txt_content = "sugarkube-terraform-lab:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  }

  expect_failures = [var.tf_lab_txt_content]
}
