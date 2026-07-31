#!/usr/bin/env ruby
# frozen_string_literal: true

require "base64"
require "yaml"

SECRETS = ["alertmanager-pagerduty", "alertmanager-healthchecks-watchdog"].freeze
PD_RECEIVER = "pagerduty-synthetic-test"
HC_RECEIVER = "healthchecks-watchdog"
PD_PATH = "/etc/alertmanager/secrets/alertmanager-pagerduty/routing-key"
HC_PATH = "/etc/alertmanager/secrets/alertmanager-healthchecks-watchdog/ping-url"
PD_MATCHERS = ['alertname="SugarkubePagerDutyTest"', 'environment="staging"',
               'cluster="sugarkube-int"', 'severity="critical"'].freeze
HC_MATCHERS = ['alertname="SugarkubeObservabilityWatchdog"', 'environment="staging"',
               'cluster="sugarkube-int"', 'purpose="observability-watchdog"'].freeze

def fail_closed(message)
  warn "ERROR: Alertmanager integration structure invalid: #{message} (sensitive values not printed)."
  exit 16
end

mode, *paths = ARGV
fail_closed("expected rendered FILE or live ALERTMANAGER_YAML CONFIG_SECRET_YAML") unless
  (mode == "rendered" && paths.length == 1) || (mode == "live" && paths.length == 2)

begin
  documents = paths.flat_map do |path|
    File.read(path).split(/^---\s*$\n?/).filter_map do |text|
      next unless text.match?(/^kind: (Alertmanager|Secret)\s*$/)
      YAML.safe_load(text, permitted_classes: [], aliases: false)
    end
  end
rescue StandardError
  fail_closed("input manifests are missing or malformed")
end

ams = documents.select { |d| d.is_a?(Hash) && d["kind"] == "Alertmanager" && d.dig("metadata", "name") == "kube-prometheus-stack-alertmanager" }
fail_closed("expected exactly one kube-prometheus-stack Alertmanager custom resource") unless ams.length == 1
fail_closed("Alertmanager must reference exactly the two expected Secrets") unless ams[0].dig("spec", "secrets") == SECRETS

secret = documents.find { |d| d.is_a?(Hash) && d["kind"] == "Secret" && d.dig("metadata", "name") == "alertmanager-kube-prometheus-stack-alertmanager" }
fail_closed("generated Alertmanager configuration Secret is missing") unless secret
begin
  encoded = secret.dig("data", "alertmanager.yaml")
  text = secret.dig("stringData", "alertmanager.yaml") || (Base64.strict_decode64(encoded) if encoded)
  config = YAML.safe_load(text, permitted_classes: [], aliases: false)
rescue StandardError
  fail_closed("generated Alertmanager configuration is missing or malformed")
end
fail_closed("generated Alertmanager configuration is malformed") unless config.is_a?(Hash)

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
fail_closed("root must have exactly the two allowlisted direct-child routes") unless children.is_a?(Array) && children.length == 2

receivers = config["receivers"]
fail_closed("receiver list is malformed") unless receivers.is_a?(Array) && receivers.all? { |r| r.is_a?(Hash) }
fail_closed("receiver list must contain exactly null, PagerDuty, and Healthchecks") unless receivers.map { |r| r["name"] } == ["null", PD_RECEIVER, HC_RECEIVER]
fail_closed('root "null" receiver is malformed') unless receivers[0] == { "name" => "null" }

pd = receivers[1]
fail_closed("there must be exactly one PagerDuty receiver") unless pd.keys.sort == %w[name pagerduty_configs] && pd["pagerduty_configs"].is_a?(Array) && pd["pagerduty_configs"].length == 1
pdc = pd["pagerduty_configs"][0]
fail_closed("PagerDuty configuration is malformed") unless pdc.is_a?(Hash)
fail_closed("PagerDuty must use the exact mounted routing-key file") unless pdc == { "routing_key_file" => PD_PATH, "send_resolved" => true }

hc = receivers[2]
fail_closed("there must be exactly one watchdog webhook receiver") unless hc.keys.sort == %w[name webhook_configs] && hc["webhook_configs"].is_a?(Array) && hc["webhook_configs"].length == 1
hcc = hc["webhook_configs"][0]
expected_hc = { "url_file" => HC_PATH, "send_resolved" => false,
                "http_config" => { "follow_redirects" => true }, "max_alerts" => 1, "timeout" => "10s" }
fail_closed("Healthchecks webhook contract changed") unless hcc == expected_hc

pd_route, hc_route = children
fail_closed("PagerDuty route must remain the first direct child") unless pd_route["receiver"] == PD_RECEIVER
fail_closed("PagerDuty route matchers are not the exact synthetic allowlist") unless pd_route == { "receiver" => PD_RECEIVER, "matchers" => PD_MATCHERS }
expected_hc_route = { "receiver" => HC_RECEIVER, "matchers" => HC_MATCHERS,
                      "group_by" => %w[alertname cluster environment], "group_wait" => "30s",
                      "group_interval" => "1m", "repeat_interval" => "5m", "continue" => false }
fail_closed("watchdog route grouping, timing, matchers, or continuation changed") unless hc_route == expected_hc_route

warn "Alertmanager PagerDuty and Healthchecks structure verified (credential values not accessed)."
