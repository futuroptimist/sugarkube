import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/observability_blackbox.sh"

def run(env):
    return subprocess.run([str(SCRIPT), "install", env], cwd=ROOT, text=True, capture_output=True, env={**os.environ, "PATH": "/usr/bin:/bin"})

def test_environment_rejection_happens_before_tools_or_mutation():
    for env in ("", "env=prod", "production", "wat"):
        result = run(env)
        assert result.returncode == 2
        assert "helm" not in result.stdout

def test_script_pins_source_and_safe_mutation_order():
    text = SCRIPT.read_text()
    assert 'REPOSITORY="https://prometheus-community.github.io/helm-charts"' in text
    assert 'CHART="prometheus-community/prometheus-blackbox-exporter"' in text
    assert '--version "$(version)" -f "$STAGING_VALUES" --wait --timeout "$TIMEOUT"' in text
    assert "--reuse-values" not in text
    assert "uninstall" not in text
    assert text.index('with_rendered; preflight; state="$(release_state)"') < text.index('helm install "$RELEASE"')
    assert text.index('helm install "$RELEASE"') < text.index('kubectl apply -f "$PROBE_RENDER"')

def test_status_and_verify_contain_no_mutations():
    text = SCRIPT.read_text()
    status = text[text.index("status()") : text.index("validate_objects()")]
    verify = text[text.index("verify()") : text.index('cmd="${1:-}"')]
    for body in (status, verify):
        assert "helm install" not in body
        assert "helm upgrade" not in body
        assert "kubectl apply" not in body

def test_justfile_has_all_lifecycle_recipes():
    text = (ROOT / "justfile").read_text()
    for command in ("render", "install", "upgrade", "status", "verify"):
        assert f"observability-blackbox-{command}" in text
        assert f"observability_blackbox.sh {command}" in text
