from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "cluster_identity.py"


def _kubectl(bin_dir: Path) -> Path:
    path = bin_dir / "kubectl"
    path.write_text(
        textwrap.dedent("""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if len(args) >= 2 and args[0] == "--kubeconfig":
    args = args[2:]
if args[:2] == ["config", "current-context"]:
    print(os.environ.get("STUB_CONTEXT", "sugar-prod")); raise SystemExit(0)
if args[:2] == ["config", "view"]:
    print("https://127.0.0.1:6443", end=""); raise SystemExit(0)
if args == ["get", "nodes", "-o", "json"]:
    mode = os.environ.get("STUB_NODES", "staging")
    if mode == "fail":
        print("api down", file=sys.stderr); raise SystemExit(7)
    if mode == "empty":
        print('{"items": []}'); raise SystemExit(0)
    if mode == "missing":
        print(json.dumps({"items":[{"metadata":{"name":"sugarkube3","labels":{"sugarkube.cluster":"cube"}}}]})); raise SystemExit(0)
    if mode == "missing-cluster":
        print(json.dumps({"items":[{"metadata":{"name":"sugarkube3","labels":{"sugarkube.env":"staging"}}}]})); raise SystemExit(0)
    if mode == "mixed-cluster":
        print(json.dumps({"items":[{"metadata":{"name":"sugarkube3","labels":{"sugarkube.env":"staging","sugarkube.cluster":"cube-a"}}},{"metadata":{"name":"sugarkube4","labels":{"sugarkube.env":"staging","sugarkube.cluster":"cube-b"}}}]})); raise SystemExit(0)
    if mode == "malformed-labels":
        print(json.dumps({"items":[{"metadata":{"name":"sugarkube3","labels":[]}}]})); raise SystemExit(0)
    if mode == "mixed":
        envs = ["staging", "prod"]
    else:
        envs = [mode, mode]
    print(json.dumps({"items":[{"metadata":{"name":f"sugarkube{i+3}","labels":{"sugarkube.env":e,"sugarkube.cluster":"cube"}}} for i,e in enumerate(envs)]}))
    raise SystemExit(0)
raise SystemExit(1)
"""),
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _run(tmp_path: Path, requested: str, mode: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _kubectl(bin_dir)
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["STUB_NODES"] = mode
    return subprocess.run(
        ["python3", str(SCRIPT), "assert", "--kubeconfig", str(kubeconfig), "--env", requested],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cluster_identity_matching_environment_succeeds(tmp_path: Path) -> None:
    assert _run(tmp_path, "staging", "staging").returncode == 0


def test_cluster_identity_legacy_int_normalizes_to_staging(tmp_path: Path) -> None:
    result = _run(tmp_path, "staging", "int")
    assert result.returncode == 0
    assert result.stdout.strip() == "staging"


def test_cluster_identity_requested_prod_detected_staging_fails_closed(tmp_path: Path) -> None:
    result = _run(tmp_path, "prod", "staging")
    assert result.returncode != 0
    assert "requested env=prod" in result.stderr
    assert "env=staging" in result.stderr
    assert "Connected nodes: sugarkube3, sugarkube4" in result.stderr


def test_cluster_identity_requested_staging_detected_prod_fails_closed(tmp_path: Path) -> None:
    result = _run(tmp_path, "staging", "prod")
    assert result.returncode != 0
    assert "requested env=staging" in result.stderr
    assert "env=prod" in result.stderr


def test_cluster_identity_zero_nodes_fails_closed(tmp_path: Path) -> None:
    assert "zero nodes" in _run(tmp_path, "prod", "empty").stderr


def test_cluster_identity_kubectl_failure_fails_closed(tmp_path: Path) -> None:
    assert "failed to query" in _run(tmp_path, "prod", "fail").stderr


def test_cluster_identity_missing_env_label_fails_closed(tmp_path: Path) -> None:
    assert "missing sugarkube.env" in _run(tmp_path, "prod", "missing").stderr


def test_cluster_identity_mixed_env_labels_fail_closed(tmp_path: Path) -> None:
    assert "mixed or ambiguous" in _run(tmp_path, "prod", "mixed").stderr


def test_cluster_identity_missing_cluster_label_fails_closed(tmp_path: Path) -> None:
    result = _run(tmp_path, "staging", "missing-cluster")
    assert result.returncode != 0
    assert "missing sugarkube.cluster" in result.stderr


def test_cluster_identity_mixed_cluster_labels_fail_closed(tmp_path: Path) -> None:
    result = _run(tmp_path, "staging", "mixed-cluster")
    assert result.returncode != 0
    assert "mixed or ambiguous sugarkube.cluster" in result.stderr


def test_cluster_identity_malformed_label_structure_fails_without_traceback(tmp_path: Path) -> None:
    result = _run(tmp_path, "staging", "malformed-labels")
    assert result.returncode != 0
    assert "missing sugarkube.env" in result.stderr
    assert "Traceback" not in result.stderr


def test_cluster_identity_detect_prints_details(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _kubectl(bin_dir)
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["STUB_NODES"] = "prod"
    env["STUB_CONTEXT"] = "sugar-prod"
    result = subprocess.run(
        ["python3", str(SCRIPT), "detect", "--kubeconfig", str(kubeconfig)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Environment: prod" in result.stdout
    assert "Cluster: cube" in result.stdout
    assert "Nodes: sugarkube3, sugarkube4" in result.stdout
    assert "Context: sugar-prod" in result.stdout
    assert "Server: https://127.0.0.1:6443" in result.stdout


def test_cluster_identity_assert_requires_env(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _kubectl(bin_dir)
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["python3", str(SCRIPT), "assert", "--kubeconfig", str(kubeconfig)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "assert requires --env" in result.stderr


# Direct in-process coverage for scripts/cluster_identity.py. The CLI-oriented
# tests above execute the helper in a subprocess, which validates operator
# behavior but does not contribute to pytest-cov patch coverage.
def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["kubectl"], returncode, stdout, stderr)


def _module():
    import importlib
    import scripts.cluster_identity as cluster_identity

    return importlib.reload(cluster_identity)


def _nodes(*entries: tuple[str, str, str]) -> str:
    return json.dumps(
        {
            "items": [
                {
                    "metadata": {
                        "name": name,
                        "labels": {
                            "sugarkube.env": env,
                            "sugarkube.cluster": cluster,
                        },
                    }
                }
                for name, env, cluster in entries
            ]
        }
    )


def test_cluster_identity_in_process_run_kubectl_sets_explicit_kubeconfig(monkeypatch) -> None:
    module = _module()
    observed: dict[str, object] = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["env"] = kwargs["env"]
        observed["text"] = kwargs["text"]
        observed["capture_output"] = kwargs["capture_output"]
        observed["check"] = kwargs["check"]
        return _completed("ok")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.run_kubectl("/tmp/kube", ["get", "nodes"])

    assert result.stdout == "ok"
    assert observed["command"] == ["kubectl", "--kubeconfig", "/tmp/kube", "get", "nodes"]
    assert observed["env"]["KUBECONFIG"] == "/tmp/kube"
    assert observed["text"] is True
    assert observed["capture_output"] is True
    assert observed["check"] is False


def test_cluster_identity_in_process_assert_success_and_kubectl_flags(monkeypatch, capsys) -> None:
    module = _module()
    calls: list[tuple[str, list[str]]] = []

    def fake_run_kubectl(kubeconfig: str, args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append((kubeconfig, args))
        if args == ["get", "nodes", "-o", "json"]:
            return _completed(_nodes(("sugarkube3", "int", "cube"), ("sugarkube4", "int", "cube")))
        raise AssertionError(args)

    monkeypatch.setattr(module, "run_kubectl", fake_run_kubectl)
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["cluster_identity.py", "assert", "--kubeconfig", "~/kube", "--env", "staging"],
    )

    assert module.main() == 0
    assert capsys.readouterr().out.strip() == "staging"
    assert calls == [(str(Path("~/kube").expanduser()), ["get", "nodes", "-o", "json"])]
    assert module.LAST_DETAILS["clusters"] == {"cube"}
    assert module.LAST_DETAILS["nodes"] == ["sugarkube3", "sugarkube4"]


def test_cluster_identity_in_process_detect_prints_safe_info(monkeypatch, capsys) -> None:
    module = _module()

    def fake_run_kubectl(kubeconfig: str, args: list[str]) -> subprocess.CompletedProcess[str]:
        if args == ["get", "nodes", "-o", "json"]:
            return _completed(_nodes(("sugarkube3", "prod", "cube")))
        if args == ["config", "current-context"]:
            return _completed("sugar-prod\n")
        if args == ["config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}"]:
            return _completed("https://127.0.0.1:6443")
        raise AssertionError(args)

    monkeypatch.setattr(module, "run_kubectl", fake_run_kubectl)
    monkeypatch.setattr(
        module.sys, "argv", ["cluster_identity.py", "detect", "--kubeconfig", "kube"]
    )

    assert module.main() == 0
    out = capsys.readouterr().out
    assert "Environment: prod" in out
    assert "Cluster: cube" in out
    assert "Context: sugar-prod" in out
    assert "Server: https://127.0.0.1:6443" in out


def test_cluster_identity_in_process_mismatch_reports_diagnostics(monkeypatch, capsys) -> None:
    module = _module()

    def fake_run_kubectl(kubeconfig: str, args: list[str]) -> subprocess.CompletedProcess[str]:
        if args == ["get", "nodes", "-o", "json"]:
            return _completed(
                _nodes(("sugarkube3", "staging", "cube"), ("sugarkube4", "staging", "cube"))
            )
        if args == ["config", "current-context"]:
            return _completed("misleading-sugar-prod\n")
        if args == ["config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}"]:
            return _completed("https://10.0.0.5:6443")
        raise AssertionError(args)

    monkeypatch.setattr(module, "run_kubectl", fake_run_kubectl)
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["cluster_identity.py", "assert", "--kubeconfig", "kube", "--env", "prod"],
    )

    assert module.main() == 1
    err = capsys.readouterr().err
    assert "requested env=prod" in err
    assert "Detected env(s): staging" in err
    assert "Cluster label(s): cube" in err
    assert "Context: misleading-sugar-prod" in err
    assert "Server: https://10.0.0.5:6443" in err
    assert "Connected nodes: sugarkube3, sugarkube4" in err


def test_cluster_identity_in_process_fail_closed_modes(monkeypatch, capsys) -> None:
    module = _module()
    scenarios = [
        (_completed("", 7, "api down"), "failed to query Kubernetes nodes"),
        (_completed("not-json"), "malformed node JSON"),
        (_completed(json.dumps({"items": []})), "zero nodes"),
        (
            _completed(
                json.dumps(
                    {
                        "items": [
                            {"metadata": {"name": "node1", "labels": {"sugarkube.cluster": "cube"}}}
                        ]
                    }
                )
            ),
            "missing sugarkube.env",
        ),
        (
            _completed(
                json.dumps(
                    {
                        "items": [
                            {"metadata": {"name": "node1", "labels": {"sugarkube.env": "staging"}}}
                        ]
                    }
                )
            ),
            "missing sugarkube.cluster",
        ),
        (_completed(_nodes(("node1", "qa", "cube"))), "malformed sugarkube.env"),
        (
            _completed(_nodes(("node1", "staging", "cube-a"), ("node2", "staging", "cube-b"))),
            "mixed or ambiguous sugarkube.cluster",
        ),
        (
            _completed(_nodes(("node1", "staging", "cube"), ("node2", "prod", "cube"))),
            "mixed or ambiguous sugarkube.env",
        ),
        (
            _completed(json.dumps({"items": [{"metadata": {"name": "node1", "labels": []}}]})),
            "missing sugarkube.env",
        ),
    ]

    for completed, expected in scenarios:

        def fake_run_kubectl(
            kubeconfig: str, args: list[str], completed=completed
        ) -> subprocess.CompletedProcess[str]:
            if args == ["get", "nodes", "-o", "json"]:
                return completed
            return (
                _completed("unknown\n") if args == ["config", "current-context"] else _completed("")
            )

        monkeypatch.setattr(module, "run_kubectl", fake_run_kubectl)
        code, detected = module.load_identity("kube", "prod")
        assert (code, detected) == (1, None)
        assert expected in capsys.readouterr().err


def test_cluster_identity_in_process_main_returns_load_failure(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "load_identity", lambda kubeconfig, requested: (1, None))
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["cluster_identity.py", "detect", "--kubeconfig", "kube"],
    )

    assert module.main() == 1


def test_cluster_identity_in_process_argument_validation(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module.sys, "argv", ["cluster_identity.py", "assert", "--kubeconfig", "kube"]
    )
    assert module.main() == 1
    assert "assert requires --env" in capsys.readouterr().err

    monkeypatch.setattr(
        module.sys, "argv", ["cluster_identity.py", "assert", "--kubeconfig", "kube", "--env", "qa"]
    )
    assert module.main() == 1
    assert "env must be one of" in capsys.readouterr().err
