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

begin
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
rescue StandardError
  fail_closed("input manifests are missing or malformed")
end
alertmanagers = documents.select do |doc|
  doc["kind"] == "Alertmanager" && doc.dig("metadata", "name") == "kube-prometheus-stack-alertmanager"
end
fail_closed("expected exactly one kube-prometheus-stack Alertmanager custom resource") unless alertmanagers.length == 1
alertmanager = alertmanagers.first
secrets = alertmanager.dig("spec", "secrets")
fail_closed("Alertmanager must reference only #{EXPECTED_SECRET}") unless secrets == [EXPECTED_SECRET]

config_secret = documents.find do |doc|
  doc["kind"] == "Secret" && doc.dig("metadata", "name") == "alertmanager-kube-prometheus-stack-alertmanager"
end
fail_closed("generated Alertmanager configuration Secret is missing") unless config_secret
encoded = config_secret.dig("data", "alertmanager.yaml")
plain = config_secret.dig("stringData", "alertmanager.yaml")
begin
  config_text = plain || (Base64.strict_decode64(encoded) if encoded)
  fail_closed("generated Alertmanager configuration is missing or malformed") unless config_text
  config = YAML.safe_load(config_text, permitted_classes: [], aliases: false)
rescue StandardError
  fail_closed("generated Alertmanager configuration is missing or malformed")
end

fail_closed("generated Alertmanager configuration is malformed") unless config.is_a?(Hash)

inline_credential = lambda do |value|
  case value
  when Hash
    value.key?("routing_key") || value.key?("service_key") || value.any? { |_key, child| inline_credential.call(child) }
  when Array
    value.any? { |child| inline_credential.call(child) }
  else
    false
  end
end
fail_closed("inline PagerDuty credentials are forbidden") if inline_credential.call(config)

route = config["route"]
fail_closed('root receiver must remain "null"') unless route.is_a?(Hash) && route["receiver"] == "null"

receivers = config["receivers"]
fail_closed("receiver list is malformed") unless receivers.is_a?(Array)
fail_closed("receiver list is malformed") unless receivers.all? { |item| item.is_a?(Hash) }
fail_closed('root "null" receiver is missing') unless receivers.count { |item| item == { "name" => "null" } } == 1
pagerduty = receivers.select { |item| item.key?("pagerduty_configs") }
fail_closed("there must be exactly one PagerDuty receiver") unless pagerduty.length == 1
fail_closed("PagerDuty receiver name changed") unless pagerduty.first["name"] == EXPECTED_RECEIVER
pd_configs = pagerduty.first["pagerduty_configs"]
fail_closed("there must be exactly one PagerDuty configuration") unless pd_configs.is_a?(Array) && pd_configs.length == 1
pd_config = pd_configs.first
fail_closed("PagerDuty configuration is malformed") unless pd_config.is_a?(Hash)
fail_closed("PagerDuty must use the exact mounted routing-key file") unless pd_config["routing_key_file"] == EXPECTED_PATH
fail_closed("PagerDuty resolved notifications must be enabled") unless pd_config["send_resolved"] == true

all_routes = []
walk_routes = lambda do |candidate|
  fail_closed("route tree is malformed") unless candidate.is_a?(Hash)
  all_routes << candidate
  children = candidate["routes"]
  return if children.nil?

  fail_closed("route tree is malformed") unless children.is_a?(Array)
  children.each { |child| walk_routes.call(child) }
end
walk_routes.call(route)
pagerduty_routes = all_routes.select { |candidate| candidate["receiver"] == EXPECTED_RECEIVER }
fail_closed("there must be exactly one PagerDuty route") unless pagerduty_routes.length == 1
synthetic_route = pagerduty_routes.first
fail_closed("PagerDuty route matchers are not the exact synthetic allowlist") unless
  synthetic_route["matchers"].is_a?(Array) && synthetic_route["matchers"].sort == EXPECTED_MATCHERS.sort
fail_closed("PagerDuty route must not specify continuation") if synthetic_route.key?("continue")

warn "Alertmanager PagerDuty structure verified (credential value not accessed)."
