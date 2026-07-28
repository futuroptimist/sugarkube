#!/usr/bin/env ruby
# frozen_string_literal: true

require "base64"
require "yaml"

EXPECTED_SECRET = "alertmanager-pagerduty"
EXPECTED_PATH = "/etc/alertmanager/secrets/alertmanager-pagerduty/routing-key"
EXPECTED_RECEIVER = "pagerduty-synthetic-test"
EXPECTED_MATCHERS = [
  'alertname="SugarkubePagerDutyTest"',
  'environment="staging"',
  'cluster="sugarkube-int"',
  'severity="critical"'
].freeze

def fail_closed(message)
  warn "ERROR: Alertmanager PagerDuty structure invalid: #{message} (sensitive values not printed)."
  exit 16
end

mode, *paths = ARGV
fail_closed("expected rendered FILE or live ALERTMANAGER_YAML CONFIG_SECRET_YAML") unless
  (mode == "rendered" && paths.length == 1) || (mode == "live" && paths.length == 2)

documents = paths.flat_map do |path|
  content = File.read(path)
  content = content[content.index("---\n")..] if mode == "rendered" && content.index("---\n")
  content.split(/^---\s*$\n?/).filter_map do |document|
    relevant = document.match?(/^kind: Alertmanager\s*$/) ||
      (document.match?(/^kind: Secret\s*$/) &&
       document.include?("name: alertmanager-kube-prometheus-stack-alertmanager"))
    YAML.safe_load(document, permitted_classes: [], aliases: false) if relevant
  end
end
alertmanager = documents.find { |doc| doc["kind"] == "Alertmanager" }
fail_closed("expected Alertmanager custom resource is missing") unless alertmanager
secrets = alertmanager.dig("spec", "secrets")
fail_closed("Alertmanager must reference only #{EXPECTED_SECRET}") unless secrets == [EXPECTED_SECRET]

config_secret = documents.find do |doc|
  doc["kind"] == "Secret" && doc.dig("metadata", "name") == "alertmanager-kube-prometheus-stack-alertmanager"
end
fail_closed("generated Alertmanager configuration Secret is missing") unless config_secret
encoded = config_secret.dig("data", "alertmanager.yaml")
plain = config_secret.dig("stringData", "alertmanager.yaml")
config_text = plain || (Base64.strict_decode64(encoded) if encoded)
fail_closed("generated Alertmanager configuration is missing or malformed") unless config_text
config = YAML.safe_load(config_text, permitted_classes: [], aliases: false)

route = config["route"]
fail_closed('root receiver must remain "null"') unless route.is_a?(Hash) && route["receiver"] == "null"
routes = route["routes"]
fail_closed("there must be exactly one PagerDuty route") unless routes.is_a?(Array) && routes.length == 1
synthetic_route = routes.first
fail_closed("PagerDuty route receiver changed") unless synthetic_route["receiver"] == EXPECTED_RECEIVER
fail_closed("PagerDuty route matchers are not the exact synthetic allowlist") unless
  synthetic_route["matchers"].is_a?(Array) && synthetic_route["matchers"].sort == EXPECTED_MATCHERS.sort
fail_closed("PagerDuty route must not continue into broader routing") if synthetic_route["continue"] == true

receivers = config["receivers"]
fail_closed("receiver list is malformed") unless receivers.is_a?(Array)
fail_closed('root "null" receiver is missing') unless receivers.count { |item| item == { "name" => "null" } } == 1
pagerduty = receivers.select { |item| item["name"] == EXPECTED_RECEIVER }
fail_closed("there must be exactly one synthetic PagerDuty receiver") unless pagerduty.length == 1
pd_configs = pagerduty.first["pagerduty_configs"]
fail_closed("there must be exactly one PagerDuty configuration") unless pd_configs.is_a?(Array) && pd_configs.length == 1
pd_config = pd_configs.first
fail_closed("PagerDuty must use the exact mounted routing-key file") unless pd_config["routing_key_file"] == EXPECTED_PATH
fail_closed("PagerDuty resolved notifications must be enabled") unless pd_config["send_resolved"] == true
fail_closed("inline PagerDuty credentials are forbidden") if pd_config.key?("routing_key") || pd_config.key?("service_key")

warn "Alertmanager PagerDuty structure verified (credential value not accessed)."
