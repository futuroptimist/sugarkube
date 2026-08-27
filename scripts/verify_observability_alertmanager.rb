#!/usr/bin/env ruby
# frozen_string_literal: true

require "base64"
require "yaml"

PD_SECRET = "alertmanager-pagerduty"
HC_SECRET = "alertmanager-healthchecks-watchdog"
PD_RECEIVER = "pagerduty-synthetic-test"
DSPACE_RECEIVER = "pagerduty-dspace"
TOKENPLACE_RECEIVER = "pagerduty-tokenplace"
HC_RECEIVER = "healthchecks-watchdog"
PD_PATH = "/etc/alertmanager/secrets/alertmanager-pagerduty/routing-key"
HC_PATH = "/etc/alertmanager/secrets/alertmanager-healthchecks-watchdog/ping-url"
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
expected_secrets = [PD_SECRET, HC_SECRET]
unless (ams.first.dig("spec", "secrets") || []) == expected_secrets
  fail_closed("#{environment} Alertmanager must reference exactly the two expected integration Secrets in order")
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
fail_closed("root route must contain only its receiver and exact child routes") unless route.keys.sort == %w[receiver routes]
children = route["routes"]
expected_route_count = environment == "prod" ? 5 : 4
fail_closed("root must have exactly the environment's allowlisted direct-child routes") unless children.is_a?(Array) && children.length == expected_route_count
receivers = config["receivers"]
expected_receiver_count = environment == "prod" ? 5 : 4
fail_closed("receiver list does not match the environment's exact integration allowlist") unless receivers.is_a?(Array) && receivers.length == expected_receiver_count && receivers.all? { |x| x.is_a?(Hash) }
fail_closed('root "null" receiver is missing or broadened') unless receivers.count { |x| x == { "name" => "null" } } == 1

pd_receivers = receivers.select { |x| x.key?("pagerduty_configs") }
expected_pd_names = [PD_RECEIVER, DSPACE_RECEIVER]
expected_pd_names << TOKENPLACE_RECEIVER if environment == "prod"
fail_closed("PagerDuty receiver names changed") unless pd_receivers.map { |x| x["name"] }.sort == expected_pd_names.sort
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

if environment == "prod"
  ds_route, cloudflare_route, tokenplace_route, pd_route, hc_route = children
else
  ds_route, cloudflare_route, pd_route, hc_route = children
end
label_environment = environment
cluster = environment == "staging" ? "sugarkube-int" : "sugarkube-prod"
pd_matchers = ['alertname="SugarkubePagerDutyTest"', "environment=\"#{label_environment}\"",
               "cluster=\"#{cluster}\"", 'severity="critical"']
hc_matchers = ['alertname="SugarkubeObservabilityWatchdog"', "environment=\"#{label_environment}\"",
               "cluster=\"#{cluster}\"", 'purpose="observability-watchdog"']
dspace_matchers = ['alertname=~"^(DspaceBuildRevisionMismatch|DspaceMixedBuildRevisions|DspaceDeploymentImagePinMismatch|DspaceChatSyntheticFailed|DspaceMetricsTargetDown)$"',
                   "environment=\"#{label_environment}\"", "cluster=\"#{cluster}\"", 'severity="critical"']
cloudflare_matchers = ['alertname="CloudflareTunnelNoHealthyConnections"',
                       "environment=\"#{label_environment}\"", "cluster=\"#{cluster}\"", 'severity="critical"']
tokenplace_matchers = ['alertname=~"^(TokenplaceNoHealthyComputeNodes|TokenplaceMetricsTargetDown)$"',
                       'environment="prod"', 'cluster="sugarkube-prod"', 'severity="critical"']
fail_closed("DSPACE route ordering or receiver changed") unless ds_route["receiver"] == DSPACE_RECEIVER
fail_closed("DSPACE route matchers are not the exact alert allowlist") unless ds_route["matchers"].is_a?(Array) && ds_route["matchers"].sort == dspace_matchers.sort
fail_closed("DSPACE route must contain only receiver and exact matchers") unless ds_route.keys.sort == %w[matchers receiver]
fail_closed("Cloudflare route ordering or receiver changed") unless cloudflare_route["receiver"] == DSPACE_RECEIVER
fail_closed("Cloudflare route matchers are not the exact critical allowlist") unless cloudflare_route["matchers"].is_a?(Array) && cloudflare_route["matchers"].sort == cloudflare_matchers.sort
fail_closed("Cloudflare route must contain only receiver and exact matchers") unless cloudflare_route.keys.sort == %w[matchers receiver]
if environment == "prod"
  fail_closed("token.place route ordering or receiver changed") unless tokenplace_route["receiver"] == TOKENPLACE_RECEIVER
  fail_closed("token.place route matchers are not the exact production alert allowlist") unless tokenplace_route["matchers"].is_a?(Array) && tokenplace_route["matchers"].sort == tokenplace_matchers.sort
  fail_closed("token.place route must contain only receiver and exact matchers") unless tokenplace_route.keys.sort == %w[matchers receiver]
end
fail_closed("PagerDuty route ordering or receiver changed") unless pd_route["receiver"] == PD_RECEIVER
fail_closed("PagerDuty route matchers are not the exact synthetic allowlist") unless pd_route["matchers"].is_a?(Array) && pd_route["matchers"].sort == pd_matchers.sort
fail_closed("PagerDuty route must contain only receiver and exact matchers") unless pd_route.keys.sort == %w[matchers receiver]
expected_hc = {
  "receiver" => HC_RECEIVER, "matchers" => hc_matchers,
  "group_by" => %w[alertname cluster environment], "group_wait" => "30s",
  "group_interval" => "1m", "repeat_interval" => "5m", "continue" => false
}
fail_closed("watchdog route is not the exact direct-child allowlist and timing contract") unless hc_route == expected_hc
warn "Alertmanager two-integration structure verified (credential values not accessed)."
