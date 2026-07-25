import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/observability_blackbox.sh"


def run(args, tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True)
    for tool in ("helm", "kubectl"):
        (bindir / tool).write_text(
            '#!/bin/sh\necho CALLED >>"$LOG"\n'
            "[ \"$1 $2\" = 'config current-context' ] && echo sugar-staging\n"
        )
        (bindir / tool).chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "LOG": str(tmp_path / "log")}
    return subprocess.run([str(SCRIPT), *args], cwd=ROOT, env=env, text=True, capture_output=True)


def test_missing_and_production_envs_fail_before_cluster_access(tmp_path):
    cases = [
        ([], "empty"),
        (["render"], "missing"),
        (["render", "prod"], "prod"),
        (["render", "production"], "production"),
        (["render", "dev"], "dev"),
    ]
    for args, dirname in cases:
        run_dir = tmp_path / dirname
        result = run(args, run_dir)
        assert result.returncode == 2
        assert not (run_dir / "log").exists()


def test_helper_has_guarded_complete_lifecycle():
    text = SCRIPT.read_text()
    assert "https://prometheus-community.github.io/helm-charts" in text
    assert '--version "$(version)" -f "${VALUES}" --wait --timeout "${TIMEOUT}"' in text
    assert "--reuse-values" not in text
    assert text.index('helm "${action}"') < text.index('kubectl apply -f "${PROBE_RENDER}"')
    assert 'environment=prod" --ignore-not-found' in text
    assert "2>/dev/null" not in text[text.index("prom_get()") : text.index("verify_series()")]
    assert "cluster_identity.py" in text and "sugar-staging" in text
    status = text[text.index("status()") : text.index("validate_resources()")]
    assert " apply " not in status and "helm install" not in status and "helm upgrade" not in status
