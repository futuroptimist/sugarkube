#!/usr/bin/env ruby
# frozen_string_literal: true

require "yaml"
require "base64"

EXPECTED_SECRET = "alertmanager-pagerduty"
EXPECTED_FILE = "/etc/alertmanager/secrets/#{EXPECTED_SECRET}/routing-key"
EXPECTED_MATCHERS = [
  'alertname="SugarkubePagerDutyTest"',
  'environment="staging"',
  'cluster="sugarkube-int"',
  'severity="critical"'
].freeze

def fail_validation(message)
  warn "ERROR: invalid staging Alertmanager configuration: #{message}"
  exit 1
end

config_only = %w[--config --base64-config].include?(ARGV.first)
base64_config = ARGV.first == "--base64-config"
ARGV.shift if config_only
path = ARGV.fetch(0) { fail_validation("manifest or configuration path is required") }
input = path == "-" ? $stdin.read : File.read(path)
if config_only
  input = Base64.strict_decode64(input) if base64_config
  config = YAML.safe_load(input, permitted_classes: [], aliases: false)
else
  documents = YAML.load_stream(input).compact
  alertmanager = documents.find do |document|
    document.is_a?(Hash) && document["kind"] == "Alertmanager" &&
      document.dig("metadata", "name") == "kube-prometheus-stack-alertmanager"
  end
  fail_validation("expected Alertmanager custom resource is missing") unless alertmanager

  secrets = alertmanager.dig("spec", "secrets")
  fail_validation("Alertmanager must reference only #{EXPECTED_SECRET}") unless secrets == [EXPECTED_SECRET]

  config_secret = documents.find do |document|
    document.is_a?(Hash) && document["kind"] == "Secret" &&
      document.dig("metadata", "name") == "alertmanager-kube-prometheus-stack-alertmanager"
  end
  fail_validation("chart-rendered Alertmanager configuration Secret is missing") unless config_secret

  raw_config = config_secret.dig("stringData", "alertmanager.yaml")
  raw_config ||= Base64.strict_decode64(config_secret.dig("data", "alertmanager.yaml").to_s)
  fail_validation("Alertmanager configuration is missing") if raw_config.empty?
  config = YAML.safe_load(raw_config, permitted_classes: [], aliases: false)
end
fail_validation('root receiver must remain "null"') unless config.dig("route", "receiver") == "null"

routes = config.dig("route", "routes")
pagerduty_routes = Array(routes).select { |route| route.is_a?(Hash) && route["receiver"] == "pagerduty-synthetic" }
unless pagerduty_routes.length == 1 && pagerduty_routes.first["matchers"] == EXPECTED_MATCHERS
  fail_validation("PagerDuty must have exactly the narrow synthetic route")
end

receivers = config["receivers"]
null_receivers = Array(receivers).select { |receiver| receiver == {"name" => "null"} }
pagerduty_receivers = Array(receivers).select do |receiver|
  receiver.is_a?(Hash) && receiver["name"] == "pagerduty-synthetic"
end
unless null_receivers.length == 1 && pagerduty_receivers.length == 1 && receivers.length == 2
  fail_validation("only the null and synthetic PagerDuty receivers are allowed")
end

pagerduty_configs = pagerduty_receivers.first["pagerduty_configs"]
unless pagerduty_configs == [{"routing_key_file" => EXPECTED_FILE, "send_resolved" => true}]
  fail_validation("PagerDuty must use the expected routing-key file with send_resolved enabled")
end

forbidden = %w[routing_key service_key]
walk = lambda do |value|
  case value
  when Hash
    fail_validation("inline PagerDuty credential fields are forbidden") unless (value.keys & forbidden).empty?
    value.each_value { |child| walk.call(child) }
  when Array
    value.each { |child| walk.call(child) }
  end
end
walk.call(config)

puts "Rendered Alertmanager route, receiver, Secret mount contract, and file reference are valid."
