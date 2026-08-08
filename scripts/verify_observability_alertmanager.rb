#!/usr/bin/env ruby
# frozen_string_literal: true

require "base64"
require "yaml"

PD_SECRET = "alertmanager-pagerduty"
HC_SECRET = "alertmanager-healthchecks-watchdog"
PD_RECEIVER = "pagerduty-synthetic-test"
DSPACE_RECEIVER = "pagerduty-dspace"
HC_RECEIVER = "healthchecks-watchdog"
PD_PATH = "/etc/alertmanager/secrets/alertmanager-pagerduty/routing-key"
HC_PATH = "/etc/alertmanager/secrets/alertmanager-healthchecks-watchdog/ping-url"
PD_MATCHERS = ['alertname="SugarkubePagerDutyTest"', 'environment="staging"',
               'cluster="sugarkube-int"', 'severity="critical"'].freeze
HC_MATCHERS = ['alertname="SugarkubeObservabilityWatchdog"', 'environment="staging"',
               'cluster="sugarkube-int"', 'purpose="observability-watchdog"'].freeze
DSPACE_MATCHERS = ['alertname=~"^(DspaceBuildRevisionMismatch|DspaceMixedBuildRevisions|DspaceDeploymentImagePinMismatch|DspaceChatSyntheticFailed|DspaceMetricsTargetDown)$"',
                   'environment="staging"', 'cluster="sugarkube-int"', 'severity="critical"'].freeze
CLOUDFLARE_MATCHERS = ['alertname=~"^(CloudflareTunnelNoConnections|CloudflareTunnelMetricsDown)$"',
                       'environment="staging"', 'cluster="sugarkube-int"', 'severity="critical"'].freeze

def fail_closed(message)
  warn "ERROR: Alertmanager integration structure invalid: #{message} (sensitive values not printed)."
  exit 16
end

environment, mode, *paths = ARGV
fail_closed("expected environment staging or prod") unless %w[staging prod].include?(environment)
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
expected_secrets = environment == "staging" ? [PD_SECRET, HC_SECRET] : []
unless (ams.first.dig("spec", "secrets") || []) == expected_secrets
  if environment == "staging"
    fail_closed("staging Alertmanager must reference exactly the two expected integration Secrets in order")
  end
  fail_closed("production Alertmanager must mount no integration Secrets")
end
secret = documents.find { |d| d.is_a?(Hash) && d["kind"] == "Secret" && d.dig("metadata", "name") == "alertmanager-kube-prometheus-stack-alertmanager" }
fail_closed("generated Alertmanager configuration Secret is missing") unless secret
begin
  raw = secret.dig("stringData", "alertmanager.yaml")
  raw ||= Base64.strict_decode64(secret.dig("data", "alertmanager.yaml"))
  config = YAML.safe_load(raw, permitted_classes: [], aliases: false)
rescue StandardError
  fail_closed("generated Alertmanager configuration is missing or malformed")
end
fail_closed("generated Alertmanager configuration is malformed") unless config.is_a?(Hash)

forbidden = lambda do |value|
  case value
  when Hash
    value.any? { |key, child| %w[routing_key service_key url].include?(key) || forbidden.call(child) }
  when Array then value.any? { |child| forbidden.call(child) }
  else false
  end
end
fail_closed("inline credentials or webhook URLs are forbidden") if forbidden.call(config)

route = config["route"]
fail_closed('root receiver must remain "null"') unless route.is_a?(Hash) && route["receiver"] == "null"
if environment == "prod"
  allowed_route = {"receiver" => "null"}
  nullable_route = {"group_by" => nil, "group_wait" => nil, "group_interval" => nil,
                    "repeat_interval" => nil, "receiver" => "null"}
  fail_closed("production root route must be the exact null-only route") unless [allowed_route, nullable_route].include?(route)
  fail_closed("production receiver list must contain only null") unless config["receivers"] == [{"name" => "null"}]
  fail_closed("production configuration must contain only route and receivers") unless config.keys.sort == %w[receivers route]
  warn "Alertmanager production null-only structure verified (credential values not accessed)."
  exit 0
end
fail_closed("root route must contain only its receiver and exact child routes") unless route.keys.sort == %w[receiver routes]
children = route["routes"]
fail_closed("root must have exactly the four allowlisted direct-child routes") unless children.is_a?(Array) && children.length == 4
receivers = config["receivers"]
fail_closed("receiver list must contain exactly null, two PagerDuty receivers, and Healthchecks") unless receivers.is_a?(Array) && receivers.length == 4 && receivers.all? { |x| x.is_a?(Hash) }
fail_closed('root "null" receiver is missing or broadened') unless receivers.count { |x| x == { "name" => "null" } } == 1

pd_receivers = receivers.select { |x| x.key?("pagerduty_configs") }
fail_closed("there must be exactly two PagerDuty receivers") unless pd_receivers.length == 2
fail_closed("PagerDuty receiver names changed") unless pd_receivers.map { |x| x["name"] }.sort == [PD_RECEIVER, DSPACE_RECEIVER].sort
pd_receivers.each do |pd|
  fail_closed("PagerDuty receiver is malformed") unless pd.keys.sort == %w[name pagerduty_configs]
  configs = pd["pagerduty_configs"]
  fail_closed("PagerDuty configuration is malformed") unless configs == [{ "routing_key_file" => PD_PATH, "send_resolved" => true }]
end

webhook_receivers = receivers.select { |x| x.key?("webhook_configs") }
fail_closed("there must be exactly one webhook receiver") unless webhook_receivers.length == 1
hc = webhook_receivers.first
fail_closed("Healthchecks receiver name changed") unless hc["name"] == HC_RECEIVER
fail_closed("Healthchecks receiver is malformed") unless hc.keys.sort == %w[name webhook_configs]
webhooks = hc["webhook_configs"]
expected_webhook = { "url_file" => HC_PATH, "send_resolved" => false, "max_alerts" => 1, "timeout" => "10s" }
fail_closed("Healthchecks webhook must use the exact file, resolution, timeout, and alert limit") unless webhooks == [expected_webhook]

ds_route, pd_route, hc_route, cloudflare_route = children
fail_closed("DSPACE route ordering or receiver changed") unless ds_route["receiver"] == DSPACE_RECEIVER
fail_closed("DSPACE route matchers are not the exact alert allowlist") unless ds_route["matchers"].is_a?(Array) && ds_route["matchers"].sort == DSPACE_MATCHERS.sort
fail_closed("DSPACE route must contain only receiver and exact matchers") unless ds_route.keys.sort == %w[matchers receiver]
fail_closed("PagerDuty route ordering or receiver changed") unless pd_route["receiver"] == PD_RECEIVER
fail_closed("PagerDuty route matchers are not the exact synthetic allowlist") unless pd_route["matchers"].is_a?(Array) && pd_route["matchers"].sort == PD_MATCHERS.sort
fail_closed("PagerDuty route must contain only receiver and exact matchers") unless pd_route.keys.sort == %w[matchers receiver]
expected_hc = {
  "receiver" => HC_RECEIVER, "matchers" => HC_MATCHERS,
  "group_by" => %w[alertname cluster environment], "group_wait" => "30s",
  "group_interval" => "1m", "repeat_interval" => "5m", "continue" => false
}
fail_closed("watchdog route is not the exact direct-child allowlist and timing contract") unless hc_route == expected_hc
fail_closed("Cloudflare route ordering or receiver changed") unless cloudflare_route["receiver"] == DSPACE_RECEIVER
fail_closed("Cloudflare route matchers are not the exact alert allowlist") unless cloudflare_route["matchers"].is_a?(Array) && cloudflare_route["matchers"].sort == CLOUDFLARE_MATCHERS.sort
fail_closed("Cloudflare route must contain only receiver and exact matchers") unless cloudflare_route.keys.sort == %w[matchers receiver]
warn "Alertmanager two-integration structure verified (credential values not accessed)."
