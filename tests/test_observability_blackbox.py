import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/observability_blackbox.sh"


def run(*args, path=""):
    env = os.environ.copy(); env["PATH"] = path
    return subprocess.run(["/bin/bash", str(SCRIPT), *args], cwd=ROOT, env=env, text=True, capture_output=True)


def test_environment_rejected_before_tools_or_cluster_access():
    for env in ("", "prod", "production", "dev", "mystery"):
        result = run("install", env)
        assert result.returncode == 2
        assert "supported" in result.stderr or "unsupported" in result.stderr


def test_script_has_guarded_distinct_complete_lifecycle():
    text = SCRIPT.read_text()
    assert "https://prometheus-community.github.io/helm-charts" in text
    assert 'assert_context' in text and 'cluster_identity.py' in text and 'sugar-staging' in text
    assert 'helm install' in text and 'helm upgrade' in text
    assert '--wait' in text and '--timeout' in text
    assert '--reuse-values' not in text
    assert 'kubectl apply -f "${probe_render}"' in text
    assert text.index('helm install') < text.index('kubectl apply -f "${probe_render}"')
    assert "uninstall" not in text


def test_status_and_verify_functions_are_read_only():
    text = SCRIPT.read_text()
    status = text[text.index("status() {"):text.index("validate_runtime_objects()")]
    verify = text[text.index("verify() {"):text.index('cmd="${1:-}"')]
    forbidden = (" apply ", " install ", " upgrade ", " delete ", " patch ")
    assert not any(word in status for word in forbidden)
    assert not any(word in verify for word in forbidden)


def test_just_recipes_cover_five_commands():
    text = (ROOT / "justfile").read_text()
    for command in ("render", "install", "upgrade", "status", "verify"):
        assert f"observability-blackbox-{command} env=''" in text
        assert f"observability_blackbox.sh {command}" in text
