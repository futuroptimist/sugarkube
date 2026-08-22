mock_provider "cloudflare" {}

variables {
  cloudflare_zone_id = "0123456789abcdef0123456789abcdef"
  tf_lab_txt_content = "sugarkube-terraform-lab:mock-test"
}

run "tf_lab_contract" {
  command = plan

  assert {
    condition     = cloudflare_dns_record.tf_lab.name == "tf-lab.gitshelves.com"
    error_message = "The only represented resource must use the disposable lab FQDN."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.type == "TXT"
    error_message = "The disposable lab record must be TXT."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.content == var.tf_lab_txt_content
    error_message = "The record must pass through the tested TXT content."
  }

  assert {
    condition     = cloudflare_dns_record.tf_lab.ttl == 300
    error_message = "The disposable lab TTL must be 300 seconds."
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

run "invalid_zone_id" {
  command = plan

  variables {
    cloudflare_zone_id = "not-a-zone-id"
  }

  expect_failures = [var.cloudflare_zone_id]
}

run "invalid_txt_prefix" {
  command = plan

  variables {
    tf_lab_txt_content = "unrecognized-content"
  }

  expect_failures = [var.tf_lab_txt_content]
}

run "oversized_txt_content" {
  command = plan

  variables {
    tf_lab_txt_content = join("", concat(["sugarkube-terraform-lab:"], [for index in range(233) : "x"]))
  }

  expect_failures = [var.tf_lab_txt_content]
}
