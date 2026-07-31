#!/usr/bin/env ruby
# frozen_string_literal: true

require "base64"
require "yaml"

EXPECTED_SECRETS = %w[alertmanager-pagerduty alertmanager-healthchecks-watchdog].freeze
PD_RECEIVER = "pagerduty-synthetic-test"
WATCHDOG_RECEIVER = "healthchecks-watchdog"
PD_MATCHERS = ['alertname="SugarkubePagerDutyTest"', 'environment="staging"', 'cluster="sugarkube-int"', 'severity="critical"'].freeze
WATCHDOG_MATCHERS = ['alertname="SugarkubeObservabilityWatchdog"', 'environment="staging"', 'cluster="sugarkube-int"', 'purpose="observability-watchdog"'].freeze

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
        (document.match?(/^kind: Secret\s*$/) && document.include?("name: alertmanager-kube-prometheus-stack-alertmanager"))
      YAML.safe_load(document, permitted_classes: [], aliases: false) if relevant
    end
  end
rescue StandardError
  fail_closed("input manifests are missing or malformed")
end
alertmanagers = documents.select { |doc| doc["kind"] == "Alertmanager" && doc.dig("metadata", "name") == "kube-prometheus-stack-alertmanager" }
fail_closed("expected exactly one kube-prometheus-stack Alertmanager custom resource") unless alertmanagers.length == 1
secrets = alertmanagers.first.dig("spec", "secrets")
fail_closed("Alertmanager must reference exactly the two expected Secrets") unless secrets == EXPECTED_SECRETS

config_secret = documents.find { |doc| doc["kind"] == "Secret" && doc.dig("metadata", "name") == "alertmanager-kube-prometheus-stack-alertmanager" }
fail_closed("generated Alertmanager configuration Secret is missing") unless config_secret
begin
  encoded = config_secret.dig("data", "alertmanager.yaml")
  text = config_secret.dig("stringData", "alertmanager.yaml") || (Base64.strict_decode64(encoded) if encoded)
  config = YAML.safe_load(text, permitted_classes: [], aliases: false) if text
rescue StandardError
  config = nil
end
fail_closed("generated Alertmanager configuration is missing or malformed") unless config.is_a?(Hash)

forbidden = lambda do |value|
  case value
  when Hash
    value.keys.any? { |key| %w[routing_key service_key url].include?(key) } || value.values.any? { |child| forbidden.call(child) }
  when Array then value.any? { |child| forbidden.call(child) }
  else false
  end
end
fail_closed("inline credentials or webhook URLs are forbidden") if forbidden.call(config)

route = config["route"]
fail_closed('root receiver must remain "null"') unless route.is_a?(Hash) && route["receiver"] == "null"
children = route["routes"]
fail_closed("root must contain exactly the two allowlisted direct-child routes") unless children.is_a?(Array) && children.length == 2
receivers = config["receivers"]
fail_closed("receiver list must contain exactly null, PagerDuty, and watchdog receivers") unless
  receivers.is_a?(Array) && receivers.all? { |item| item.is_a?(Hash) } && receivers.map { |item| item["name"] } == ["null", PD_RECEIVER, WATCHDOG_RECEIVER]
fail_closed('root "null" receiver is malformed') unless receivers[0] == { "name" => "null" }
fail_closed("there must be exactly one PagerDuty receiver") unless receivers.count { |item| item.key?("pagerduty_configs") } == 1
fail_closed("there must be exactly one webhook receiver") unless receivers.count { |item| item.key?("webhook_configs") } == 1

pd = receivers[1]
fail_closed("PagerDuty receiver name changed") unless pd["name"] == PD_RECEIVER && pd.keys.sort == %w[name pagerduty_configs]
pd_configs = pd["pagerduty_configs"]
fail_closed("there must be exactly one PagerDuty configuration") unless pd_configs.is_a?(Array) && pd_configs.length == 1
fail_closed("PagerDuty configuration changed") unless pd_configs[0] == {
  "routing_key_file" => "/etc/alertmanager/secrets/alertmanager-pagerduty/routing-key", "send_resolved" => true
}

webhook = receivers[2]
fail_closed("watchdog receiver name changed") unless webhook["name"] == WATCHDOG_RECEIVER && webhook.keys.sort == %w[name webhook_configs]
webhook_configs = webhook["webhook_configs"]
fail_closed("there must be exactly one watchdog webhook configuration") unless webhook_configs.is_a?(Array) && webhook_configs.length == 1
fail_closed("watchdog webhook configuration changed") unless webhook_configs[0] == {
  "url_file" => "/etc/alertmanager/secrets/alertmanager-healthchecks-watchdog/ping-url",
  "send_resolved" => false, "http_config" => { "follow_redirects" => true }, "max_alerts" => 1, "timeout" => "10s"
}

pd_route, watchdog_route = children
fail_closed("PagerDuty route must remain first and exact") unless pd_route == { "receiver" => PD_RECEIVER, "matchers" => PD_MATCHERS }
expected_watchdog = {
  "receiver" => WATCHDOG_RECEIVER, "matchers" => WATCHDOG_MATCHERS,
  "group_by" => %w[alertname cluster environment], "group_wait" => "30s",
  "group_interval" => "1m", "repeat_interval" => "5m", "continue" => false
}
fail_closed("watchdog route must be the exact second direct child") unless watchdog_route == expected_watchdog
fail_closed("nested or broad routes are forbidden") if children.any? { |child| child.key?("routes") }

warn "Alertmanager PagerDuty and watchdog structure verified (credential values not accessed)."
