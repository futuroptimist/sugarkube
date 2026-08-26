#!/usr/bin/env ruby
# frozen_string_literal: true

require "json"
require "yaml"

EXPECTED_RUNTIME_BYTES = 100 * 1024**3

def fail_closed(message)
  abort "ERROR: Prometheus retention verification failed: #{message}."
end

def read_json(path, endpoint)
  document = JSON.parse(File.read(path))
  fail_closed("#{endpoint} returned an unsuccessful response") unless document.is_a?(Hash) && document["status"] == "success"
  document.fetch("data")
rescue Errno::ENOENT, JSON::ParserError, KeyError, TypeError
  fail_closed("#{endpoint} response is malformed")
end

def size_bytes(value)
  match = /\A(\d+)([KMGTPE]?i?B)\z/.match(value.to_s)
  fail_closed("size retention #{value.inspect} is malformed") unless match
  exponent = { "B" => 0, "KB" => 1, "KiB" => 1, "MB" => 2, "MiB" => 2,
               "GB" => 3, "GiB" => 3, "TB" => 4, "TiB" => 4,
               "PB" => 5, "PiB" => 5, "EB" => 6, "EiB" => 6 }.fetch(match[2])
  match[1].to_i * 1024**exponent
end

begin
desired_time, desired_size, config_path, runtime_path, metrics_path, cr_path = ARGV
fail_closed("validator arguments are missing") unless ARGV.length == 6
desired_bytes = size_bytes(desired_size)

config_data = read_json(config_path, "status/config")
yaml = config_data.is_a?(Hash) ? config_data["yaml"] : nil
fail_closed("status/config response has no loaded YAML configuration") unless yaml.is_a?(String) && !yaml.empty?
loaded = YAML.safe_load(yaml, aliases: false)
retention = loaded&.dig("storage", "tsdb", "retention")
fail_closed("loaded configuration has no storage.tsdb.retention block") unless retention.is_a?(Hash)
fail_closed("loaded time retention is missing or differs from #{desired_time}") unless retention["time"] == desired_time
loaded_bytes = size_bytes(retention["size"])
fail_closed("loaded size retention is not equivalent to #{desired_size}") unless loaded_bytes == desired_bytes

runtime = read_json(runtime_path, "status/runtimeinfo")
fail_closed("runtime configuration reload was unsuccessful") unless runtime.is_a?(Hash) && runtime["reloadConfigSuccess"] == true

metrics = File.read(metrics_path)
limits = metrics.scan(/^prometheus_tsdb_retention_limit_bytes(?:\{[^\n]*\})?\s+([^\s]+)(?:\s+\d+)?$/).flatten
fail_closed("runtime size-retention limit is missing or ambiguous") unless limits.length == 1
limit = Float(limits.first)
fail_closed("runtime size-retention limit is zero or differs from #{desired_bytes} bytes") unless limit.positive? && limit == desired_bytes && limit == EXPECTED_RUNTIME_BYTES

cr = JSON.parse(File.read(cr_path))
spec = cr.fetch("spec")
fail_closed("Prometheus CR must have one replica") unless spec["replicas"] == 1
fail_closed("Prometheus CR time retention differs from #{desired_time}") unless spec["retention"] == desired_time
fail_closed("Prometheus CR size retention is not equivalent to #{desired_size}") unless size_bytes(spec["retentionSize"]) == desired_bytes

puts "Prometheus loaded/runtime retention confirmed: #{desired_time}, #{desired_bytes} bytes, reload successful."
rescue Errno::ENOENT, JSON::ParserError, Psych::Exception, KeyError, TypeError, ArgumentError
  fail_closed("runtime metrics or Prometheus CR response is malformed")
end
