#!/usr/bin/env python3
"""Export the Helm-owned DSPACE rule group as a promtool-compatible rule file."""

import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = root / "clusters/staging/observability/kube-prometheus-stack.values.yaml"
if len(sys.argv) != 2:
    raise SystemExit(f"usage: {sys.argv[0]} OUTPUT")
loaded = json.loads(
    subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.safe_load_file(ARGV[0], aliases: true))",
            str(source),
        ],
        check=True,
        text=True,
        capture_output=True,
    ).stdout
)
groups = loaded["additionalPrometheusRulesMap"]["dspace-release-integrity"]["groups"]
out = Path(sys.argv[1])
rendered = subprocess.run(
    ["ruby", "-ryaml", "-e", "puts YAML.dump({'groups' => JSON.parse(STDIN.read)})"],
    input=json.dumps(groups),
    text=True,
    capture_output=True,
    check=True,
    env={**__import__("os").environ, "RUBYOPT": "-rjson"},
).stdout
out.write_text(rendered, encoding="utf-8")
