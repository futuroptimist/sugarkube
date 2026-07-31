#!/usr/bin/env ruby
# frozen_string_literal: true

require "base64"
require "yaml"

EXPECTED_SECRETS = %w[alertmanager-pagerduty alertmanager-healthchecks-watchdog].freeze
PAGERDUTY_PATH = "/etc/alertmanager/secrets/alertmanager-pagerduty/routing-key"
WATCHDOG_PATH = "/etc/alertmanager/secrets/alertmanager-healthchecks-watchdog/ping-url"
PAGERDUTY_RECEIVER = "pagerduty-synthetic-test"
WATCHDOG_RECEIVER = "healthchecks-watchdog"
PAGERDUTY_MATCHERS = [
  'alertname="SugarkubePagerDutyTest"',
  'environment="staging"',
  'cluster="sugarkube-int"',
  'severity="critical"'
].freeze
WATCHDOG_MATCHERS = [
  'alertname="SugarkubeObservabilityWatchdog"',
  'environment="staging"',
  'cluster="sugarkube-int"',
  'purpose="observability-watchdog"'
].freeze

def fail_closed(message)
  warn "ERROR: Alertmanager integration structure invalid: #{message} (sensitive values not printed)."
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
fail_closed("Alertmanager must reference exactly the two expected Secrets") unless secrets == EXPECTED_SECRETS

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
    value.key?("routing_key") || value.key?("service_key") || value.key?("url") ||
      value.any? { |_key, child| inline_credential.call(child) }
  when Array
    value.any? { |child| inline_credential.call(child) }
  else
    false
  end
end
fail_closed("inline credentials and webhook URLs are forbidden") if inline_credential.call(config)

route = config["route"]
fail_closed('root receiver must remain "null"') unless route.is_a?(Hash) && route["receiver"] == "null"

receivers = config["receivers"]
fail_closed("receiver list is malformed") unless receivers.is_a?(Array)
fail_closed("receiver list is malformed") unless receivers.all? { |item| item.is_a?(Hash) }
fail_closed('root "null" receiver is missing') unless receivers.count { |item| item == { "name" => "null" } } == 1
fail_closed("exactly three receivers are required") unless receivers.length == 3
pagerduty = receivers.select { |item| item.key?("pagerduty_configs") }
fail_closed("there must be exactly one PagerDuty receiver") unless pagerduty.length == 1
fail_closed("PagerDuty receiver name changed") unless pagerduty.first["name"] == PAGERDUTY_RECEIVER
pd_configs = pagerduty.first["pagerduty_configs"]
fail_closed("there must be exactly one PagerDuty configuration") unless pd_configs.is_a?(Array) && pd_configs.length == 1
pd_config = pd_configs.first
fail_closed("PagerDuty configuration is malformed") unless pd_config.is_a?(Hash)
fail_closed("PagerDuty must use the exact mounted routing-key file") unless pd_config == {
  "routing_key_file" => PAGERDUTY_PATH, "send_resolved" => true
}
fail_closed("PagerDuty resolved notifications must be enabled") unless pd_config["send_resolved"] == true

webhooks = receivers.select { |item| item.key?("webhook_configs") }
fail_closed("there must be exactly one webhook receiver") unless webhooks.length == 1
fail_closed("watchdog receiver name changed") unless webhooks.first["name"] == WATCHDOG_RECEIVER
webhook_configs = webhooks.first["webhook_configs"]
fail_closed("there must be exactly one watchdog webhook configuration") unless webhook_configs.is_a?(Array) && webhook_configs.length == 1
fail_closed("watchdog webhook must use only the mounted URL file and exact delivery contract") unless webhook_configs.first == {
  "url_file" => WATCHDOG_PATH, "send_resolved" => false, "max_alerts" => 1, "timeout" => "10s"
}

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
pagerduty_routes = all_routes.select { |candidate| candidate["receiver"] == PAGERDUTY_RECEIVER }
fail_closed("there must be exactly one PagerDuty route") unless pagerduty_routes.length == 1
synthetic_route = pagerduty_routes.first
root_children = route["routes"]
fail_closed("PagerDuty route must be a direct child of the root route") unless
  root_children.is_a?(Array) && root_children.include?(synthetic_route)
fail_closed("PagerDuty route matchers are not the exact synthetic allowlist") unless
  synthetic_route["matchers"].is_a?(Array) && synthetic_route["matchers"].sort == PAGERDUTY_MATCHERS.sort
fail_closed("PagerDuty route must not contain nested routes") if synthetic_route.key?("routes")
fail_closed("PagerDuty route must not specify continuation") if synthetic_route.key?("continue")

watchdog_routes = all_routes.select { |candidate| candidate["receiver"] == WATCHDOG_RECEIVER }
fail_closed("there must be exactly one watchdog route") unless watchdog_routes.length == 1
watchdog_route = watchdog_routes.first
fail_closed("watchdog route must be the second direct child of the null root") unless
  root_children == [synthetic_route, watchdog_route]
fail_closed("watchdog route matchers are not the exact allowlist") unless
  watchdog_route["matchers"].is_a?(Array) && watchdog_route["matchers"].sort == WATCHDOG_MATCHERS.sort
expected_route_fields = {
  "receiver" => WATCHDOG_RECEIVER, "matchers" => watchdog_route["matchers"],
  "group_wait" => "30s", "group_interval" => "1m", "repeat_interval" => "5m",
  "group_by" => %w[alertname cluster environment]
}
fail_closed("watchdog grouping, timing, continuation, or nesting changed") unless watchdog_route == expected_route_fields
known_receivers = ["null", PAGERDUTY_RECEIVER, WATCHDOG_RECEIVER]
fail_closed("route tree contains an unexpected or broad receiver") unless all_routes.all? { |candidate| known_receivers.include?(candidate["receiver"]) }

warn "Alertmanager PagerDuty and watchdog structure verified (credential values not accessed)."
