"""Deterministic, host-isolated tests for the repository-owned synthetic producer."""

from __future__ import annotations

import copy
import json
import os
import grp
import pwd
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from scripts import dspace_chat_synthetic_runtime as runtime
from scripts import install_dspace_chat_synthetic as installer

materializer = installer

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/dspace-chat-synthetic.json"


def config(tmp_path: Path) -> dict:
    value = json.loads(CONFIG.read_text(encoding="utf-8"))
    value.update(
        runnerRoot=str(tmp_path / "runners"),
        resultRoot=str(tmp_path / "results"),
        metricPath=str(tmp_path / "metric.prom"),
        metricsConsumer=str(tmp_path / "consumer.py"),
    )
    value["browserContract"] = {"name": "runner-local-playwright-v1"}
    return value


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def source_repo(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "source"
    source.mkdir()
    git("init", cwd=source)
    git("config", "user.email", "tests@example.invalid", cwd=source)
    git("config", "user.name", "Tests", cwd=source)
    git("remote", "add", "origin", "https://github.com/democratizedspace/dspace.git", cwd=source)
    (source / "package.json").write_text("{}\n")
    git("add", "package.json", cwd=source)
    git("commit", "-m", "fixture", cwd=source)
    return source, git("rev-parse", "HEAD", cwd=source)


def test_configuration_selects_contracts_and_exact_legacy_coordinate(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    value = config(tmp_path)
    path.write_text(json.dumps(value))
    assert runtime.load_config(path)["providerConfigContract"] == "legacy-no-default-provider-v1"
    for key in ("identityContract", "providerConfigContract"):
        broken = copy.deepcopy(value)
        broken.pop(key)
        path.write_text(json.dumps(broken))
        with pytest.raises(runtime.Invalid):
            runtime.load_config(path)
    broken = copy.deepcopy(value)
    broken["dspaceVersion"] = "3.1.2"
    path.write_text(json.dumps(broken))
    with pytest.raises(runtime.Invalid, match="coordinate"):
        runtime.load_config(path)
    broken = copy.deepcopy(value)
    broken["schemaVersion"] = 2
    path.write_text(json.dumps(broken))
    with pytest.raises(runtime.Invalid, match="schema"):
        runtime.load_config(path)


@pytest.mark.parametrize(
    ("key", "replacement", "message"),
    [
        ("repositoryIdentity", "https://example.invalid/dspace.git", "repository identity"),
        ("tokenPlaceOrigin", "https://token.place", "token.place origin"),
        ("tokenPlaceModel", "different-model", "token.place model"),
        ("serviceAccount", "../../root", "service identifier"),
        ("serviceGroup", "group name", "service identifier"),
        ("serviceAccount", 123, "value type"),
        ("runnerRevision", None, "value type"),
        ("timeoutSeconds", "30", "value type"),
        ("timeoutSeconds", True, "value type"),
    ],
)
def test_configuration_rejects_coordinate_drift_and_malformed_types(
    tmp_path: Path, key: str, replacement: object, message: str
) -> None:
    path = tmp_path / "config.json"
    value = config(tmp_path)
    value[key] = replacement
    path.write_text(json.dumps(value))

    with pytest.raises(runtime.Invalid, match=message):
        runtime.load_config(path)


@pytest.mark.parametrize(
    ("key", "replacement", "message"),
    [
        ("runnerRevision", "not-a-revision", "runner coordinate"),
        ("identityContract", "unknown", "identity contract"),
        ("providerConfigContract", "unknown", "provider contract"),
        ("provider", "other", "provider or timeout"),
        ("timeoutSeconds", 0, "provider or timeout"),
        ("dspaceOrigin", "https://example.invalid", "DSPACE origin"),
        ("runnerRoot", "relative", "configured path"),
    ],
)
def test_configuration_rejects_remaining_invalid_contract_values(
    tmp_path: Path, key: str, replacement: object, message: str
) -> None:
    path = tmp_path / "config.json"
    value = config(tmp_path)
    value[key] = replacement
    path.write_text(json.dumps(value))

    with pytest.raises(runtime.Invalid, match=message):
        runtime.load_config(path)


def system_browser_config(tmp_path: Path) -> tuple[dict, Path]:
    value = config(tmp_path)
    root = tmp_path / "target"
    launcher = root / "usr/bin/chromium"
    executable = root / "usr/lib/chromium/chromium"
    launcher.parent.mkdir(parents=True)
    executable.parent.mkdir(parents=True)
    launcher.write_text('#!/bin/sh\nexec /usr/lib/chromium/chromium "$@"\n')
    executable.write_text("browser\n")
    launcher.chmod(0o755)
    executable.chmod(0o755)
    value["browserContract"] = {
        "name": "system-chromium-v1",
        "architecture": "aarch64",
        "launcherPath": "/usr/bin/chromium",
        "launcherRealPath": "/usr/bin/chromium",
        "launcherSha256": runtime.sha256(launcher),
        "executablePath": "/usr/lib/chromium/chromium",
        "executableRealPath": "/usr/lib/chromium/chromium",
        "executableSha256": runtime.sha256(executable),
        "owner": pwd.getpwuid(os.getuid()).pw_name,
        "group": grp.getgrgid(os.getgid()).gr_name,
        "mode": "0755",
    }
    return value, root


def test_explicit_system_browser_contract_validates_exact_target_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, root = system_browser_config(tmp_path)
    monkeypatch.setattr(runtime.platform, "machine", lambda: "aarch64")
    observed = runtime.validate_browser_contract(value, root)
    assert observed["name"] == "system-chromium-v1"
    assert observed["executablePath"] == "/usr/lib/chromium/chromium"
    assert not (root / "playwright-browser").exists()


@pytest.mark.parametrize(
    "fault", ["architecture", "launcher-hash", "executable-hash", "mode", "realpath", "same-path"]
)
def test_system_browser_contract_drift_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    value, root = system_browser_config(tmp_path)
    monkeypatch.setattr(
        runtime.platform, "machine", lambda: "x86_64" if fault == "architecture" else "aarch64"
    )
    contract = value["browserContract"]
    if fault == "launcher-hash":
        contract["launcherSha256"] = "0" * 64
    elif fault == "executable-hash":
        contract["executableSha256"] = "0" * 64
    elif fault == "mode":
        (root / "usr/lib/chromium/chromium").chmod(0o700)
    elif fault == "realpath":
        contract["executableRealPath"] = "/usr/lib/chromium/other"
    elif fault == "same-path":
        contract["executablePath"] = contract["launcherPath"]
    with pytest.raises((runtime.Invalid, FileNotFoundError)):
        runtime.validate_browser_contract(value, root)


def test_runtime_system_contract_plumbs_exact_executable_without_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, _metric, _sibling, calls = prepare_runtime_run(tmp_path, monkeypatch)
    value["browserContract"] = {"name": "system-chromium-v1"}
    monkeypatch.setattr(
        runtime,
        "validate_browser_contract",
        lambda _config: {
            "name": "system-chromium-v1",
            "executablePath": "/usr/lib/chromium/chromium",
        },
    )
    assert runtime.run(value) == 0
    child = next(call for call in calls if call["argv"][0] == "runuser")
    assert child["env"]["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"] == "/usr/lib/chromium/chromium"
    assert child["env"]["PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"] == "1"
    assert "PLAYWRIGHT_BROWSERS_PATH" not in child["env"]


def test_runtime_main_reports_success_and_bounded_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config(tmp_path)))
    monkeypatch.setattr(sys, "argv", ["runtime", "--config", str(path)])
    monkeypatch.setattr(runtime, "run", lambda value: 7)
    assert runtime.main() == 7

    monkeypatch.setattr(runtime, "run", lambda value: (_ for _ in ()).throw(runtime.Invalid("x")))
    assert runtime.main() == 1
    assert capsys.readouterr().out == "outcome=preserved reason=preflight\n"


def runtime_runner(tmp_path: Path) -> tuple[dict, Path]:
    value = config(tmp_path)
    runner = Path(value["runnerRoot"]) / "fixture"
    runner.mkdir(parents=True)
    git("init", cwd=runner)
    git("config", "user.email", "tests@example.invalid", cwd=runner)
    git("config", "user.name", "Tests", cwd=runner)
    required = {
        "scripts/run-remote-chat-smoke.mjs": "// runner\n",
        "scripts/remote-chat-smoke-completion.mjs": "// completion\n",
        "frontend/e2e/remote-chat-smoke.spec.ts": "// smoke\n",
        "package.json": "{}\n",
        "frontend/package.json": "{}\n",
        "pnpm-workspace.yaml": "packages: []\n",
        "pnpm-lock.yaml": "lockfileVersion: '9.0'\n",
        "playwright-browser/browser-executable": "#!/bin/sh\nexit 0\n",
    }
    for relative, contents in required.items():
        target = runner / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
    (runner / "playwright-browser/browser-executable").chmod(0o755)
    cli = runner / "frontend/node_modules/.bin/playwright"
    cli.parent.mkdir(parents=True)
    cli.write_text("#!/bin/sh\nexit 0\n")
    cli.chmod(0o755)
    (runner / "node_modules/.pnpm").mkdir(parents=True)
    module = runner / "frontend/node_modules/@playwright/test"
    module.mkdir(parents=True)
    (module / "package.json").write_text('{"main":"index.js"}\n')
    (module / "index.js").write_text("module.exports = {};\n")
    git("add", ".", cwd=runner)
    git("commit", "-m", "runtime fixture", cwd=runner)
    revision = git("rev-parse", "HEAD", cwd=runner)
    destination = Path(value["runnerRoot"]) / revision
    runner.rename(destination)
    value["runnerRevision"] = revision
    manifest = {
        "schemaVersion": 1,
        "runnerRevision": revision,
        "repositoryIdentity": runtime.APPROVED_REPOSITORY_IDENTITY,
        "browserContract": {"name": "runner-local-playwright-v1"},
        "playwrightBrowserExecutable": "playwright-browser/browser-executable",
        "files": {relative: runtime.sha256(destination / relative) for relative in required},
    }
    (destination / "sugarkube-runner-manifest.json").write_text(json.dumps(manifest))
    return value, destination


def test_runner_validation_accepts_complete_independent_git_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, runner = runtime_runner(tmp_path)
    real_run = subprocess.run

    def fake_node(argv, *args, **kwargs):
        if argv[0] == "/usr/bin/node":
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=str(runner / "playwright-browser/browser-executable").encode(),
            )
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(runtime.subprocess, "run", fake_node)

    assert runtime.validate_runner(value) == runner


def test_runner_validation_rejects_missing_git_metadata(tmp_path: Path) -> None:
    value, runner = runtime_runner(tmp_path)
    (runner / ".git").rename(runner / "incomplete-git")

    with pytest.raises(runtime.Invalid, match="complete Git metadata"):
        runtime.validate_runner(value)


@pytest.mark.parametrize("fault", ["shallow", "fsck"])
def test_runner_validation_rejects_shallow_or_failed_fsck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    value, _ = runtime_runner(tmp_path)
    real_run = subprocess.run

    def controlled_run(argv, *args, **kwargs):
        if "--is-shallow-repository" in argv and fault == "shallow":
            return subprocess.CompletedProcess(argv, 0, stdout="true\n", stderr="")
        if "fsck" in argv and fault == "fsck":
            raise subprocess.CalledProcessError(1, argv)
        if argv[0] == "/usr/bin/node":
            runner = Path(value["runnerRoot"]) / value["runnerRevision"]
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=str(runner / "playwright-browser/browser-executable").encode(),
            )
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(runtime.subprocess, "run", controlled_run)
    expected = runtime.Invalid if fault == "shallow" else subprocess.CalledProcessError
    with pytest.raises(expected):
        runtime.validate_runner(value)


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("invalid-file-entry", "critical file manifest"),
        ("unsafe-file-entry", "critical file manifest"),
        ("browser-manifest", "Playwright browser manifest"),
        ("missing-required", "critical file manifest"),
        ("missing-store", "root pnpm store"),
        ("missing-cli", "Playwright CLI"),
        ("browser-mismatch", "Playwright browser manifest"),
    ],
)
def test_runner_validation_rejects_incomplete_snapshot_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str, message: str
) -> None:
    value, runner = runtime_runner(tmp_path)
    manifest_path = runner / "sugarkube-runner-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if fault == "invalid-file-entry":
        manifest["files"]["package.json"] = 1
    elif fault == "unsafe-file-entry":
        manifest["files"]["../outside"] = "0" * 64
    elif fault == "browser-manifest":
        manifest["playwrightBrowserExecutable"] = "package.json"
    elif fault == "missing-required":
        manifest["files"].pop("pnpm-lock.yaml")
    elif fault == "missing-store":
        (runner / "node_modules/.pnpm").rmdir()
    elif fault == "missing-cli":
        (runner / "frontend/node_modules/.bin/playwright").unlink()
    manifest_path.write_text(json.dumps(manifest))

    discovered = runner / "playwright-browser/browser-executable"
    if fault == "browser-mismatch":
        other = runner / "playwright-browser/other"
        other.write_text("#!/bin/sh\n")
        other.chmod(0o755)
        discovered = other
    real_run = subprocess.run

    def controlled_run(argv, *args, **kwargs):
        if argv[0] == "/usr/bin/node":
            return subprocess.CompletedProcess(argv, 0, stdout=str(discovered).encode())
        if "status" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(runtime.subprocess, "run", controlled_run)
    with pytest.raises(runtime.Invalid, match=message):
        runtime.validate_runner(value)


def prepare_runtime_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, result_kind: str = "valid"
) -> tuple[dict, Path, Path, list[dict]]:
    value = config(tmp_path)
    root = Path(value["resultRoot"])
    root.mkdir()
    runner = tmp_path / "runner"
    runner.mkdir()
    consumer = Path(value["metricsConsumer"])
    consumer.write_text("#!/bin/sh\n")
    consumer.chmod(0o755)
    metric = Path(value["metricPath"])
    metric.write_bytes(b"previous metric\n")
    sibling = root / f"uid-1000-{'b' * 32}"
    sibling.mkdir()
    (sibling / "keep").write_text("untouched")
    account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid(), pw_dir="/tmp", pw_name="pi")
    monkeypatch.setenv("INVOCATION_ID", "a" * 32)
    monkeypatch.setenv("SECRET_PARENT_TOKEN", "must-not-leak")
    monkeypatch.setattr(runtime.pwd, "getpwnam", lambda _name: account)
    monkeypatch.setattr(runtime.grp, "getgrnam", lambda _name: SimpleNamespace(gr_gid=os.getgid()))
    monkeypatch.setattr(runtime, "validate_runner", lambda _config: runner)
    monkeypatch.setattr(
        runtime,
        "validate_browser_contract",
        lambda _config: {
            "name": "runner-local-playwright-v1",
            "executablePath": str(runner / "playwright-browser/browser-executable"),
        },
    )
    monkeypatch.setattr(runtime, "validate_dir", lambda *_args: None)
    monkeypatch.setattr(runtime.os, "chown", lambda *_args: None)
    calls: list[dict] = []

    def fake_run(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        if argv[0] == "runuser":
            result = root / f"uid-{os.getuid()}-{'a' * 32}" / "result.json"
            if result_kind == "timeout":
                raise subprocess.TimeoutExpired(argv, value["timeoutSeconds"], output=b"secret")
            if result_kind == "oversized":
                result.write_bytes(b"x" * (runtime.MAX_RESULT_BYTES + 1))
                result.chmod(0o600)
            elif result_kind == "symlink":
                outside = tmp_path / "outside-result"
                outside.write_text("{}")
                result.symlink_to(outside)
            elif result_kind == "missing":
                pass
            elif result_kind == "malformed-json":
                result.write_bytes(b"\xffnot-json")
                result.chmod(0o600)
            else:
                executed_at = (
                    99 if result_kind == "stale" else 101 if result_kind == "future" else 100
                )
                payload = {
                    "schemaVersion": 1,
                    "journey": "chat",
                    "passed": True,
                    "executedAt": executed_at,
                    "runnerRevision": value["runnerRevision"],
                    "transport": "remote",
                    "mutationEnabled": False,
                }
                if result_kind == "malformed-schema":
                    payload.pop("journey")
                temporary = result.parent / ".result.tmp"
                temporary.write_text(json.dumps(payload))
                temporary.chmod(0o600)
                os.replace(temporary, result)
                if result_kind == "hard-linked":
                    os.link(result, sibling / "shared-result")
            return subprocess.CompletedProcess(argv, 0)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)
    monkeypatch.setattr(runtime.time, "time", lambda: 100)
    return value, metric, sibling, calls


def test_runtime_run_uses_minimal_environment_and_cleans_direct_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, _metric, sibling, calls = prepare_runtime_run(tmp_path, monkeypatch)

    assert runtime.run(value) == 0
    child = next(call for call in calls if call["argv"][0] == "runuser")
    assert "SECRET_PARENT_TOKEN" not in child["env"]
    assert child["env"]["PLAYWRIGHT_BROWSERS_PATH"].endswith("playwright-browser")
    separator = child["argv"].index("--")
    node_argv = child["argv"][separator + 1 :]
    assert node_argv[0] == "/usr/bin/node"
    assert node_argv.count("--expected-provider") == 1
    provider_index = node_argv.index("--expected-provider")
    assert node_argv[provider_index + 1] == value["provider"] == "token-place"
    assert not (Path(value["resultRoot"]) / f"uid-{os.getuid()}-{'a' * 32}").exists()
    assert (sibling / "keep").read_text() == "untouched"


@pytest.mark.parametrize(
    "result_kind",
    [
        "oversized",
        "symlink",
        "hard-linked",
        "stale",
        "future",
        "missing",
        "malformed-json",
        "malformed-schema",
    ],
)
def test_runtime_run_rejects_unbounded_or_replaced_result_without_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, result_kind: str
) -> None:
    value, metric, sibling, calls = prepare_runtime_run(tmp_path, monkeypatch, result_kind)

    assert runtime.run(value) == 1
    assert metric.read_bytes() == b"previous metric\n"
    assert not any(call["argv"][0] == "/usr/bin/python3" for call in calls)
    assert (sibling / "keep").read_text() == "untouched"
    if result_kind == "hard-linked":
        assert (sibling / "shared-result").is_file()
    assert not (Path(value["resultRoot"]) / f"uid-{os.getuid()}-{'a' * 32}").exists()


def test_runtime_timeout_is_bounded_single_launch_and_owner_scoped_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value, metric, sibling, calls = prepare_runtime_run(tmp_path, monkeypatch, "timeout")

    assert runtime.run(value) == 1
    output = capsys.readouterr().out
    assert "reason=execution-error" in output
    assert "secret" not in output
    assert sum(call["argv"][0] == "runuser" for call in calls) == 1
    assert not any(call["argv"][0] == "/usr/bin/python3" for call in calls)
    assert metric.read_bytes() == b"previous metric\n"
    assert (sibling / "keep").read_text() == "untouched"
    assert not (Path(value["resultRoot"]) / f"uid-{os.getuid()}-{'a' * 32}").exists()


def test_runtime_rejects_pre_existing_invocation_without_cleanup_or_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, metric, sibling, calls = prepare_runtime_run(tmp_path, monkeypatch)
    invocation = Path(value["resultRoot"]) / f"uid-{os.getuid()}-{'a' * 32}"
    invocation.mkdir()
    (invocation / "pre-existing").write_text("untouched")

    with pytest.raises(runtime.Invalid, match="pre-existing"):
        runtime.run(value)

    assert (invocation / "pre-existing").read_text() == "untouched"
    assert (sibling / "keep").read_text() == "untouched"
    assert metric.read_bytes() == b"previous metric\n"
    assert not calls


def test_runtime_overlap_closes_lock_and_does_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, metric, _sibling, calls = prepare_runtime_run(tmp_path, monkeypatch)
    before = len(list(Path("/proc/self/fd").iterdir()))
    monkeypatch.setattr(
        runtime.fcntl, "flock", lambda *_args: (_ for _ in ()).throw(BlockingIOError())
    )

    with pytest.raises(runtime.Invalid, match="overlapping"):
        runtime.run(value)

    assert len(list(Path("/proc/self/fd").iterdir())) == before
    assert metric.read_bytes() == b"previous metric\n"
    assert not calls


def test_wrapper_safety() -> None:
    wrapper = (ROOT / "scripts/dspace_chat_synthetic_wrapper.sh").read_text()
    assert "set +x\nset -Eeuo pipefail\numask 077\nexport PYTHONDONTWRITEBYTECODE=1" in wrapper
    source = (ROOT / "scripts/dspace_chat_synthetic_runtime.py").read_text()
    assert source.count("subprocess.DEVNULL") >= 4


@pytest.mark.parametrize("condition", ["wrong-head", "dirty", "missing-object", "identity"])
def test_source_verification_rejects_invalid_git_state(tmp_path: Path, condition: str) -> None:
    source, revision = source_repo(tmp_path)
    identity = "https://github.com/democratizedspace/dspace.git"
    if condition == "wrong-head":
        wanted = "0" * 40
    elif condition == "missing-object":
        wanted = "1" * 40
    elif condition == "dirty":
        (source / "package.json").write_text('{"dirty":true}\n')
        wanted = revision
    else:
        identity = "https://example.invalid/wrong.git"
        wanted = revision
    with pytest.raises((ValueError, subprocess.SubprocessError)):
        materializer.verify_source(source, wanted, identity)


def test_source_verification_rejects_incomplete_metadata(tmp_path: Path) -> None:
    source = tmp_path / "export"
    source.mkdir()
    with pytest.raises(ValueError, match="metadata"):
        materializer.verify_source(source, "0" * 40, "identity")


def materialization_fixture(tmp_path: Path) -> tuple[Path, str, Path, Path]:
    source, _ = source_repo(tmp_path)
    for relative in materializer.CRITICAL:
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text("{}\n" if target.suffix == ".json" else "fixture\n")
    git("add", ".", cwd=source)
    git("commit", "-m", "runner files", cwd=source)
    revision = git("rev-parse", "HEAD", cwd=source)
    browser_bundle = tmp_path / "browser-input"
    browser = browser_bundle / "chromium/chrome"
    browser.parent.mkdir(parents=True)
    browser.write_text("#!/bin/sh\nexit 0\n")
    browser.chmod(0o755)
    pnpm = tmp_path / "fake-pnpm"
    pnpm.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = --version ]; then echo 9.1.0; exit; fi\n'
        "mkdir -p node_modules/.pnpm frontend/node_modules/.bin "
        "frontend/node_modules/@playwright/test\n"
        "printf '#!/bin/sh\\n' > frontend/node_modules/.bin/playwright\n"
        "chmod +x frontend/node_modules/.bin/playwright\n"
        'printf \'{"main":"index.js"}\\n\' > '
        "frontend/node_modules/@playwright/test/package.json\n"
        "printf \"const path=require('path'); exports.chromium={executablePath:()=>"
        "path.join(process.env.PLAYWRIGHT_BROWSERS_PATH,'chromium/chrome')};\\n\" > "
        "frontend/node_modules/@playwright/test/index.js\n"
    )
    pnpm.chmod(0o755)
    return source, revision, browser_bundle, pnpm


def test_materialize_discovers_browser_and_is_source_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not Path("/usr/bin/node").is_file():
        # TODO: Environments running this test should provide /usr/bin/node.
        # Root cause: The test intentionally uses the absolute production Node path,
        # while some development and test images omit it.
        # Estimated fix: Provision Node at /usr/bin/node in the affected environment.
        pytest.skip("runtime contract requires /usr/bin/node")
    source, revision, browser_bundle, pnpm = materialization_fixture(tmp_path)
    output = tmp_path / "output" / revision
    monkeypatch.setattr(installer, "runtime_module", lambda: runtime)

    materializer.materialize(
        source,
        revision,
        runtime.APPROVED_REPOSITORY_IDENTITY,
        output,
        str(pnpm),
        "9.1.0",
        browser_bundle,
    )
    manifest = json.loads((output / "sugarkube-runner-manifest.json").read_text())
    relative = manifest["playwrightBrowserExecutable"]
    assert relative == "playwright-browser/chromium/chrome"
    assert manifest["files"][relative] == runtime.sha256(output / relative)

    __import__("shutil").rmtree(source)
    __import__("shutil").rmtree(browser_bundle)
    value = config(tmp_path)
    value.update(runnerRoot=str(output.parent), runnerRevision=revision)
    assert runtime.validate_runner(value) == output


def test_materialize_orchestrates_complete_snapshot_without_host_node(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cover deterministic snapshot construction independently of Node availability."""
    source, revision, browser_bundle, pnpm = materialization_fixture(tmp_path)
    output = tmp_path / "output" / revision
    discovered = Path("playwright-browser/chromium/chrome")
    validations = []

    class CanonicalRuntime:
        @staticmethod
        def load_config(_path: Path) -> dict:
            return {"browserContract": {"name": "system-chromium-v1"}}

        @staticmethod
        def discover_playwright_browser(runner: Path) -> Path:
            return runner / discovered

    def validate_snapshot(snapshot: Path, expected_revision: str) -> None:
        validations.append((snapshot, expected_revision))
        assert (snapshot / discovered).is_file()

    monkeypatch.setattr(installer, "runtime_module", lambda: CanonicalRuntime)
    monkeypatch.setattr(installer, "validate_runner", validate_snapshot)

    installer.materialize(
        source,
        revision,
        runtime.APPROVED_REPOSITORY_IDENTITY,
        output,
        str(pnpm),
        "9.1.0",
        browser_bundle,
    )

    manifest = json.loads((output / "sugarkube-runner-manifest.json").read_text())
    assert manifest["playwrightBrowserExecutable"] == str(discovered)
    assert manifest["files"][str(discovered)] == runtime.sha256(output / discovered)
    assert validations[-1] == (output, revision)


def test_materialize_cli_dispatches_complete_coordinates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    browser = tmp_path / "browser"
    captured = []
    monkeypatch.setattr(installer, "materialize", lambda *args: captured.append(args))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "install_dspace_chat_synthetic.py",
            "materialize",
            "--source",
            str(source),
            "--output",
            str(output),
            "--pnpm",
            "/fixture/pnpm",
            "--pnpm-version",
            "9.0.0",
            "--browser-bundle",
            str(browser),
            "--browser-contract",
            "runner-local-playwright-v1",
        ],
    )

    assert installer.main() == 0
    assert captured == [
        (
            source.resolve(),
            "97ab09f13fb098de928a878bf1fe9b8d13032cb5",
            runtime.APPROVED_REPOSITORY_IDENTITY,
            output.resolve(),
            "/fixture/pnpm",
            "9.0.0",
            browser.resolve(),
            "runner-local-playwright-v1",
        )
    ]


@pytest.mark.parametrize("fault", ["outside", "missing", "non-executable"])
def test_playwright_browser_discovery_rejects_invalid_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    runner = tmp_path / "runner"
    (runner / "frontend").mkdir(parents=True)
    browser = runner / "playwright-browser/chromium/chrome"
    browser.parent.mkdir(parents=True)
    browser.write_text("browser")
    browser.chmod(0o755)
    discovered = tmp_path / "outside" if fault == "outside" else browser
    if fault == "missing":
        browser.unlink()
    elif fault == "non-executable":
        browser.chmod(0o644)
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=str(discovered).encode()
        ),
    )

    with pytest.raises(runtime.Invalid, match="discovery"):
        runtime.discover_playwright_browser(runner)


def test_playwright_browser_discovery_rejects_missing_root_and_invalid_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = tmp_path / "runner"
    (runner / "frontend").mkdir(parents=True)
    with pytest.raises(runtime.Invalid, match="discovery"):
        runtime.discover_playwright_browser(runner)

    (runner / "playwright-browser").mkdir()
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=b""),
    )
    with pytest.raises(runtime.Invalid, match="discovery"):
        runtime.discover_playwright_browser(runner)


def test_playwright_browser_discovery_rejects_symlinked_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, runner = runtime_runner(tmp_path)
    browser_root = runner / "playwright-browser"
    external_root = tmp_path / "external-browser"
    browser_root.rename(external_root)
    browser_root.symlink_to(external_root, target_is_directory=True)
    external_browser = external_root / "browser-executable"
    real_run = subprocess.run

    def controlled_run(argv, *args, **kwargs):
        if argv[0] == "/usr/bin/node":
            return subprocess.CompletedProcess(argv, 0, stdout=str(external_browser).encode())
        if "status" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(runtime.subprocess, "run", controlled_run)

    with pytest.raises(runtime.Invalid, match="discovery"):
        runtime.discover_playwright_browser(runner)
    with pytest.raises(runtime.Invalid, match="discovery"):
        runtime.validate_runner(value)


def test_playwright_browser_discovery_rejects_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = tmp_path / "runner"
    browser = runner / "playwright-browser/chromium/chrome"
    browser.parent.mkdir(parents=True)
    browser.write_text("browser")
    browser.chmod(0o755)
    (runner / "frontend").mkdir()
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=b"playwright-browser/chromium/chrome"
        ),
    )

    with pytest.raises(runtime.Invalid, match="discovery"):
        runtime.discover_playwright_browser(runner)


def test_runner_validation_rejects_discovered_browser_hash_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, runner = runtime_runner(tmp_path)
    browser = runner / "playwright-browser/browser-executable"
    browser.write_text("#!/bin/sh\nexit 7\n")
    real_run = subprocess.run

    def controlled_run(argv, *args, **kwargs):
        if "status" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if argv[0] == "/usr/bin/node":
            return subprocess.CompletedProcess(argv, 0, stdout=str(browser).encode())
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(runtime.subprocess, "run", controlled_run)

    with pytest.raises(runtime.Invalid, match="critical file hash"):
        runtime.validate_runner(value)


def snapshot(tmp_path: Path) -> tuple[Path, str]:
    source, revision = source_repo(tmp_path)
    target = tmp_path / "snapshot"
    git("clone", "--local", "--no-hardlinks", str(source), str(target), cwd=tmp_path)
    (target / "node_modules/.pnpm").mkdir(parents=True)
    cli = target / "node_modules/.bin/playwright"
    cli.parent.mkdir(parents=True)
    cli.write_text("#!/bin/sh\nexit 0\n")
    cli.chmod(0o755)
    (target / "frontend/node_modules").mkdir(parents=True)
    return target, revision


@pytest.mark.parametrize("fault", ["alternates", "store", "cli", "broken-link"])
def test_snapshot_validation_rejects_external_or_incomplete_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    target, revision = snapshot(tmp_path)
    monkeypatch.setattr(
        materializer, "command", lambda *a, **k: revision if "rev-parse" in a else ""
    )
    if fault == "alternates":
        path = target / ".git/objects/info/alternates"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("/external/objects\n")
    elif fault == "store":
        (target / "node_modules/.pnpm").rmdir()
    elif fault == "cli":
        (target / "node_modules/.bin/playwright").chmod(0o644)
    else:
        (target / "frontend/node_modules/broken").symlink_to("/absent")
    with pytest.raises(ValueError):
        materializer.validate_runner(target, revision)


def test_runner_validation_rejects_coordinate_and_hash_mismatch(tmp_path: Path) -> None:
    value = config(tmp_path)
    runner = Path(value["runnerRoot"]) / value["runnerRevision"]
    runner.mkdir(parents=True)
    (runner / "sugarkube-runner-manifest.json").write_text(json.dumps({"runnerRevision": "0" * 40}))
    with pytest.raises(runtime.Invalid, match="coordinate"):
        runtime.validate_runner(value)


@pytest.mark.parametrize("files", [{}, {"../outside": "0" * 64}, {"package.json": "bad"}])
def test_runner_validation_rejects_invalid_manifest_files(tmp_path: Path, files: dict) -> None:
    value = config(tmp_path)
    runner = Path(value["runnerRoot"]) / value["runnerRevision"]
    runner.mkdir(parents=True)
    manifest = {
        "schemaVersion": 1,
        "runnerRevision": value["runnerRevision"],
        "repositoryIdentity": value["repositoryIdentity"],
        "files": files,
    }
    (runner / "sugarkube-runner-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(runtime.Invalid, match="manifest|coordinate"):
        runtime.validate_runner(value)


def test_directory_mode_ownership_checks(tmp_path: Path) -> None:
    path = tmp_path / "results"
    path.mkdir(mode=0o710)
    info = path.stat()
    runtime.validate_dir(path, info.st_uid, info.st_gid, 0o710)
    path.chmod(0o770)
    with pytest.raises(runtime.Invalid, match="ownership or mode"):
        runtime.validate_dir(path, info.st_uid, info.st_gid, 0o710)


def test_metrics_consumer_success_failure_malformed_and_atomic_preservation(tmp_path: Path) -> None:
    from scripts.dspace_chat_synthetic_metrics import main as consumer_main

    revision = "9" * 40
    result, output = tmp_path / "result.json", tmp_path / "metric.prom"
    output.write_bytes(b"prior-metric-byte-for-byte\n")
    base = {
        "schemaVersion": 1,
        "journey": "/chat",
        "executedAt": int(__import__("time").time()),
        "runnerRevision": revision,
        "transport": "intercepted",
        "mutationEnabled": False,
    }
    import sys

    for passed, expected in ((True, " 1\n"), (False, " 0\n")):
        result.write_text(json.dumps({**base, "passed": passed}))
        monkey = [
            "consumer",
            "--result",
            str(result),
            "--output",
            str(output),
            "--runner-revision",
            revision,
        ]
        old, sys.argv = sys.argv, monkey
        try:
            assert consumer_main() == 0
        finally:
            sys.argv = old
        assert expected in output.read_text()
        assert not list(tmp_path.glob(".dspace-chat.*"))
    previous = output.read_bytes()
    result.write_text('{"rawSecret":"do-not-print"}')
    old, sys.argv = sys.argv, [
        "consumer",
        "--result",
        str(result),
        "--output",
        str(output),
        "--runner-revision",
        revision,
    ]
    try:
        with pytest.raises(SystemExit):
            consumer_main()
    finally:
        sys.argv = old
    assert output.read_bytes() == previous


def test_installer_dry_run_status_apply_and_exact_rollback(tmp_path: Path, capsys) -> None:
    before = set(tmp_path.rglob("*"))
    with __import__("tempfile").TemporaryDirectory() as temporary:
        staged = Path(temporary)
        installer.render(staged)
        installer.validate(staged)
    assert set(tmp_path.rglob("*")) == before
    assert installer.status(tmp_path) == 0
    assert "sha256=missing" in capsys.readouterr().out
    with __import__("tempfile").TemporaryDirectory() as temporary:
        staged = Path(temporary)
        installer.render(staged)
        installer.install(staged, tmp_path, "a" * 40)
    current = tmp_path / "var/lib/sugarkube/dspace-chat-installations/current"
    assert os.readlink(current) == "a" * 40
    retained = current.parent / ("a" * 40)
    installer.activate(retained, tmp_path, "a" * 40)
    with pytest.raises((OSError, ValueError)):
        installer.activate(current.parent / ("b" * 40), tmp_path, "b" * 40)
    with pytest.raises(ValueError, match="asset revision"):
        installer.activate(retained, tmp_path, "../escape")


class StatusRuntime:
    @staticmethod
    def load_config(path: Path) -> dict:
        return json.loads(path.read_text())

    @staticmethod
    def validate_runner(value: dict, _root: Path = Path("/")) -> Path:
        runner = Path(value["runnerRoot"]) / value["runnerRevision"]
        if (runner / "invalid").exists():
            raise ValueError("runner validation failed")
        return runner

    @staticmethod
    def validate_browser_contract(value: dict, _root: Path = Path("/")) -> dict:
        return {"name": value["browserContract"]["name"], "architecture": "aarch64"}


def status_installation(tmp_path: Path) -> tuple[Path, Path, str]:
    root = tmp_path / "root"
    revision = "a" * 64
    staged = tmp_path / "staged"
    installer.render(staged)
    installer.install(staged, root, revision)
    config_value = json.loads(CONFIG.read_text())
    runner = root / config_value["runnerRoot"].removeprefix("/") / config_value["runnerRevision"]
    runner.mkdir(parents=True)
    (runner / "sugarkube-runner-manifest.json").write_text(
        json.dumps(
            {
                "pnpmVersion": "9.0.0",
                "playwrightBrowserExecutable": None,
                "browserContract": config_value["browserContract"],
            }
        )
    )
    return root, runner, revision


def tree_bytes(root: Path) -> list[tuple[str, str, bytes | str]]:
    values = []
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            values.append((relative, "symlink", os.readlink(path)))
        elif path.is_file():
            values.append((relative, "file", path.read_bytes()))
        else:
            values.append((relative, "directory", b""))
    return values


def test_status_reports_validated_provenance_without_mutation_or_systemctl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    root, runner, revision = status_installation(tmp_path)
    before = tree_bytes(root)
    monkeypatch.setattr(installer, "runtime_module", lambda: StatusRuntime())
    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("alternate-root status queried systemctl"),
    )

    assert installer.status(root) == 0

    output = capsys.readouterr().out
    config_value = json.loads(CONFIG.read_text())
    assert f"assetRevision={revision}" in output
    assert f"runnerRevision={config_value['runnerRevision']}" in output
    assert (
        f"runnerManifestSha256={installer.sha(runner / 'sugarkube-runner-manifest.json')}" in output
    )
    for key in (
        "dspaceVersion",
        "dspaceSourceRevision",
        "repositoryIdentity",
        "identityContract",
        "providerConfigContract",
        "provider",
        "tokenPlaceOrigin",
        "tokenPlaceModel",
        "dspaceOrigin",
    ):
        assert f"{key}={config_value[key]}" in output
    assert "pnpmVersion=9.0.0" in output
    assert "browserName=system-chromium-v1" in output
    assert "browserArchitecture=aarch64" in output
    assert "runnerValidation=passed" in output
    assert "activation=not-queried" in output
    assert tree_bytes(root) == before


@pytest.mark.parametrize(
    "fault",
    ["current-absolute", "current-traversal", "missing-retained", "retained-hash", "live-hash"],
)
def test_status_fails_closed_for_invalid_asset_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    root, _, revision = status_installation(tmp_path)
    installations = root / "var/lib/sugarkube/dspace-chat-installations"
    current = installations / "current"
    if fault in {"current-absolute", "current-traversal"}:
        current.unlink()
        current.symlink_to("/tmp/external" if fault == "current-absolute" else "../escape")
    elif fault == "missing-retained":
        __import__("shutil").rmtree(installations / revision)
    elif fault == "retained-hash":
        (installations / revision / next(iter(installer.ASSETS))).write_bytes(b"tampered")
    else:
        (root / next(iter(installer.ASSETS))).write_bytes(b"tampered")
    monkeypatch.setattr(installer, "runtime_module", lambda: StatusRuntime())

    with pytest.raises((ValueError, FileNotFoundError, json.JSONDecodeError)):
        installer.status(root)


def test_status_fails_closed_on_runner_validation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, runner, _ = status_installation(tmp_path)
    (runner / "invalid").write_text("invalid\n")
    monkeypatch.setattr(installer, "runtime_module", lambda: StatusRuntime())

    with pytest.raises(ValueError, match="runner validation failed"):
        installer.status(root)


@pytest.mark.parametrize("fault", ["runner-symlink", "manifest-symlink", "missing-pnpm"])
def test_status_fails_closed_on_invalid_runner_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    root, runner, _ = status_installation(tmp_path)
    manifest = runner / "sugarkube-runner-manifest.json"
    if fault == "runner-symlink":
        external = tmp_path / "external-runner"
        runner.rename(external)
        runner.symlink_to(external, target_is_directory=True)
    elif fault == "manifest-symlink":
        external = tmp_path / "external-manifest.json"
        manifest.rename(external)
        manifest.symlink_to(external)
    else:
        value = json.loads(manifest.read_text())
        value.pop("pnpmVersion")
        manifest.write_text(json.dumps(value))
    monkeypatch.setattr(installer, "runtime_module", lambda: StatusRuntime())

    with pytest.raises(ValueError, match="installed runner"):
        installer.status(root)


def test_activation_status_inspects_active_and_enabled_without_mutation(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    calls = []

    def inspect(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout="active\n")

    monkeypatch.setattr(installer.shutil, "which", lambda name: "/usr/bin/systemctl")
    monkeypatch.setattr(installer.subprocess, "run", inspect)

    assert installer.activation_status() == 0
    assert [call[0] for call in calls] == [
        ["systemctl", "is-active", "dspace-chat-synthetic.service"],
        ["systemctl", "is-enabled", "dspace-chat-synthetic.service"],
        ["systemctl", "is-active", "dspace-chat-synthetic.timer"],
        ["systemctl", "is-enabled", "dspace-chat-synthetic.timer"],
    ]
    assert all(call[1]["capture_output"] and not call[1]["check"] for call in calls)
    assert all(call[1]["timeout"] == 5 for call in calls)
    assert "active=active enabled=active" in capsys.readouterr().out


def test_failed_installer_preflight_leaves_installation_unchanged(tmp_path: Path) -> None:
    marker = tmp_path / "installed"
    marker.write_bytes(b"unchanged")
    staged = tmp_path / "bad-stage"
    staged.mkdir()
    (staged / "manifest.json").write_text("{}")
    with pytest.raises(ValueError):
        installer.install(staged, tmp_path, "c" * 40)
    assert marker.read_bytes() == b"unchanged"


def run_installer_main(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["install_dspace_chat_synthetic.py", *args])
    return installer.main()


def runner_snapshot_fixture(tmp_path: Path) -> tuple[Path, str]:
    revision = "97ab09f13fb098de928a878bf1fe9b8d13032cb5"
    snapshot = tmp_path / "source" / revision
    snapshot.mkdir(parents=True)
    (snapshot / ".git").mkdir()
    (snapshot / "dependency.ok").write_text("complete\n")
    (snapshot / "sugarkube-runner-manifest.json").write_text("manifest\n")
    return snapshot, revision


class FakeSnapshotRuntime:
    def __init__(self, fail_copy: bool = False):
        self.fail_copy = fail_copy
        self.validated = []

    @staticmethod
    def load_config(path: Path) -> dict:
        return json.loads(path.read_text())

    def validate_runner(self, config: dict, _root: Path = Path("/")) -> Path:
        runner = Path(config["runnerRoot"]) / config["runnerRevision"]
        self.validated.append(runner)
        if not (runner / ".git").is_dir():
            raise ValueError("complete Git metadata")
        if not (runner / "sugarkube-runner-manifest.json").is_file():
            raise ValueError("missing manifest")
        if (runner / "hash-mismatch").exists():
            raise ValueError("critical file hash")
        if not (runner / "dependency.ok").is_file():
            raise ValueError("dependency invalid")
        if self.fail_copy and ".validate." in str(runner):
            raise ValueError("copied runner validation failed")
        return runner


@pytest.mark.parametrize(
    "fault",
    ["absent", "wrong-revision", "symlink", "hash-mismatch", "incomplete-git", "dependency"],
)
def test_installer_snapshot_preflight_rejects_invalid_input_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    snapshot, revision = runner_snapshot_fixture(tmp_path)
    if fault == "absent":
        snapshot = snapshot.parent / revision
        __import__("shutil").rmtree(snapshot)
    elif fault == "wrong-revision":
        wrong = snapshot.with_name("0" * 40)
        snapshot.rename(wrong)
        snapshot = wrong
    elif fault == "symlink":
        real = snapshot.with_name("real")
        snapshot.rename(real)
        snapshot.symlink_to(real, target_is_directory=True)
    elif fault == "hash-mismatch":
        (snapshot / "hash-mismatch").write_text("bad\n")
    elif fault == "incomplete-git":
        (snapshot / ".git").rmdir()
    else:
        (snapshot / "dependency.ok").unlink()
    root = tmp_path / "root"
    root.mkdir()
    marker = root / "marker"
    marker.write_bytes(b"unchanged")
    fake = FakeSnapshotRuntime()
    monkeypatch.setattr(installer, "runtime_module", lambda: fake)

    with pytest.raises((ValueError, SystemExit)):
        run_installer_main(
            monkeypatch,
            "apply",
            "--root",
            str(root),
            "--runner-snapshot",
            str(snapshot),
        )

    assert marker.read_bytes() == b"unchanged"
    assert not (root / "var").exists()


def test_complete_installer_dry_run_is_byte_for_byte_non_mutating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, _ = runner_snapshot_fixture(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    marker = root / "marker"
    marker.write_bytes(b"unchanged")
    before = [(str(path.relative_to(root)), path.read_bytes()) for path in root.rglob("*")]
    monkeypatch.setattr(installer, "runtime_module", lambda: FakeSnapshotRuntime())

    assert (
        run_installer_main(
            monkeypatch, "dry-run", "--root", str(root), "--runner-snapshot", str(snapshot)
        )
        == 0
    )

    after = [(str(path.relative_to(root)), path.read_bytes()) for path in root.rglob("*")]
    assert after == before


def test_apply_installs_runner_only_after_copy_revalidation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, revision = runner_snapshot_fixture(tmp_path)
    root = tmp_path / "root"
    fake = FakeSnapshotRuntime()
    monkeypatch.setattr(installer, "runtime_module", lambda: fake)

    assert (
        run_installer_main(
            monkeypatch, "apply", "--root", str(root), "--runner-snapshot", str(snapshot)
        )
        == 0
    )

    installed = root / "var/lib/sugarkube/dspace-chat-runners" / revision
    assert (installed / "dependency.ok").read_bytes() == (snapshot / "dependency.ok").read_bytes()
    assert any(".validate." in str(path) for path in fake.validated)
    assert os.readlink(root / "var/lib/sugarkube/dspace-chat-installations/current")


def test_install_runner_reuses_existing_runner_with_identical_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, revision = runner_snapshot_fixture(tmp_path)
    staged = tmp_path / "staged"
    installer.render(staged)
    root = tmp_path / "root"
    destination = root / "var/lib/sugarkube/dspace-chat-runners" / revision
    __import__("shutil").copytree(snapshot, destination)
    marker = destination / "existing-only"
    marker.write_bytes(b"preserved")
    monkeypatch.setattr(installer, "runtime_module", lambda: FakeSnapshotRuntime())

    installed, created = installer.install_runner(staged, snapshot, root)

    assert (installed, created) == (destination, False)
    assert marker.read_bytes() == b"preserved"


def test_apply_rejects_different_valid_existing_runner_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, revision = runner_snapshot_fixture(tmp_path)
    staged = tmp_path / "staged"
    installer.render(staged)
    root = tmp_path / "root"
    destination = root / "var/lib/sugarkube/dspace-chat-runners" / revision
    __import__("shutil").copytree(snapshot, destination)
    (destination / "sugarkube-runner-manifest.json").write_text("different-valid-manifest\n")
    live_asset = root / next(iter(installer.ASSETS))
    live_asset.parent.mkdir(parents=True)
    live_asset.write_bytes(b"live asset")
    retained = root / "var/lib/sugarkube/dspace-chat-installations" / ("1" * 64)
    retained.mkdir(parents=True)
    retained_marker = retained / "marker"
    retained_marker.write_bytes(b"retained")
    current = retained.parent / "current"
    current.symlink_to(retained.name)
    monkeypatch.setattr(installer, "runtime_module", lambda: FakeSnapshotRuntime())
    monkeypatch.setattr(
        installer, "install", lambda *args: pytest.fail("asset activation was invoked")
    )

    with pytest.raises(ValueError, match="existing runner manifest does not match snapshot"):
        installer.apply_installation(staged, snapshot, root, "2" * 64)

    assert live_asset.read_bytes() == b"live asset"
    assert retained_marker.read_bytes() == b"retained"
    assert (destination / "sugarkube-runner-manifest.json").read_text() == (
        "different-valid-manifest\n"
    )
    assert os.readlink(current) == retained.name
    assert not (retained.parent / ("2" * 64)).exists()


@pytest.mark.parametrize("failure", ["copied-runner", "asset-activation"])
def test_apply_failure_preserves_prior_state_and_removes_only_new_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    snapshot, revision = runner_snapshot_fixture(tmp_path)
    root = tmp_path / "root"
    prior_runner = root / "var/lib/sugarkube/dspace-chat-runners" / ("1" * 40)
    prior_runner.mkdir(parents=True)
    (prior_runner / "kept").write_bytes(b"runner")
    current = root / "var/lib/sugarkube/dspace-chat-installations/current"
    current.parent.mkdir(parents=True)
    current.symlink_to("1" * 64)
    fake = FakeSnapshotRuntime(fail_copy=failure == "copied-runner")
    monkeypatch.setattr(installer, "runtime_module", lambda: fake)
    if failure == "asset-activation":
        monkeypatch.setattr(
            installer, "install", lambda *args: (_ for _ in ()).throw(OSError("injected"))
        )

    with pytest.raises((OSError, ValueError)):
        run_installer_main(
            monkeypatch, "apply", "--root", str(root), "--runner-snapshot", str(snapshot)
        )

    assert (prior_runner / "kept").read_bytes() == b"runner"
    assert os.readlink(current) == "1" * 64
    assert not (prior_runner.parent / revision).exists()


@pytest.mark.parametrize(
    "fault",
    ["tree-symlink", "manifest-symlink", "asset-symlink", "intermediate-symlink"],
)
def test_validate_rejects_retained_asset_symlinks(tmp_path: Path, fault: str) -> None:
    real = tmp_path / "real"
    installer.render(real)
    tree = real
    if fault == "tree-symlink":
        tree = tmp_path / "tree"
        tree.symlink_to(real, target_is_directory=True)
    elif fault == "manifest-symlink":
        manifest = real / "manifest.json"
        external = tmp_path / "external-manifest.json"
        manifest.rename(external)
        manifest.symlink_to(external)
    elif fault == "asset-symlink":
        asset = real / next(iter(installer.ASSETS))
        external = tmp_path / "external-asset"
        external.write_bytes(asset.read_bytes())
        asset.unlink()
        asset.symlink_to(external)
    else:
        intermediate = real / "usr/local"
        external = tmp_path / "external-directory"
        intermediate.rename(external)
        intermediate.symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError):
        installer.validate(tree)


def test_rollback_rejects_symlinked_retained_asset_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior_revision = "1" * 64
    prior = tmp_path / "var/lib/sugarkube/dspace-chat-installations" / prior_revision
    installer.render(prior)
    installer.activate(prior, tmp_path, prior_revision)
    revision = "2" * 64
    retained = prior.parent / revision
    installer.render(retained)
    asset = retained / next(iter(installer.ASSETS))
    external = tmp_path / "matching-external-asset"
    external.write_bytes(asset.read_bytes())
    asset.unlink()
    asset.symlink_to(external)
    before = tree_bytes(tmp_path)
    monkeypatch.setattr(
        installer, "activate", lambda *args: pytest.fail("invalid rollback was activated")
    )

    with pytest.raises(ValueError):
        run_installer_main(monkeypatch, "rollback", "--root", str(tmp_path), "--revision", revision)

    assert tree_bytes(tmp_path) == before


def test_status_rejects_symlinked_retained_asset_without_systemctl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revision = "3" * 64
    retained = tmp_path / "var/lib/sugarkube/dspace-chat-installations" / revision
    installer.render(retained)
    current = retained.parent / "current"
    current.symlink_to(revision)
    asset = retained / next(iter(installer.ASSETS))
    external = tmp_path / "matching-status-asset"
    external.write_bytes(asset.read_bytes())
    asset.unlink()
    asset.symlink_to(external)
    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("invalid status queried systemctl"),
    )

    with pytest.raises(ValueError):
        installer.status(tmp_path)


@pytest.mark.parametrize("fault", ["absent", "incomplete", "hash-mismatch"])
def test_rollback_cli_rejects_invalid_retained_revision_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    revision = "d" * 40
    retained = tmp_path / "var/lib/sugarkube/dspace-chat-installations" / revision
    if fault != "absent":
        installer.render(retained)
        if fault == "incomplete":
            (retained / "manifest.json").write_text("{}")
        else:
            (retained / next(iter(installer.ASSETS))).write_bytes(b"tampered")
    marker = tmp_path / "installed-marker"
    marker.write_bytes(b"unchanged")
    monkeypatch.setattr(
        installer,
        "activate",
        lambda *args: pytest.fail("rollback activated before retained assets validated"),
    )

    with pytest.raises((FileNotFoundError, ValueError)):
        run_installer_main(monkeypatch, "rollback", "--root", str(tmp_path), "--revision", revision)

    assert marker.read_bytes() == b"unchanged"
    assert not (retained.parent / "current").exists()


def test_rollback_cli_rejects_traversal_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "installed-marker"
    marker.write_bytes(b"unchanged")
    with pytest.raises(ValueError, match="asset revision"):
        run_installer_main(
            monkeypatch, "rollback", "--root", str(tmp_path), "--revision", "../escape"
        )
    assert marker.read_bytes() == b"unchanged"
    assert not (tmp_path / "var").exists()


def test_rollback_cli_validates_dry_run_without_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    revision = "e" * 64
    retained = tmp_path / "var/lib/sugarkube/dspace-chat-installations" / revision
    installer.render(retained)
    monkeypatch.setattr(
        installer, "activate", lambda *args: pytest.fail("dry-run activated rollback")
    )

    assert (
        run_installer_main(monkeypatch, "rollback", "--root", str(tmp_path), "--revision", revision)
        == 0
    )
    assert capsys.readouterr().out == (
        "validation=passed mutation=none rollback=authorization-required\n"
    )
    assert not (retained.parent / "current").exists()


def test_rollback_cli_apply_activates_only_after_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revision = "f" * 40
    retained = tmp_path / "var/lib/sugarkube/dspace-chat-installations" / revision
    installer.render(retained)
    calls = []

    def activate(validated: Path, root: Path, selected: str) -> None:
        calls.append((validated, root, selected))

    monkeypatch.setattr(installer, "activate", activate)
    assert (
        run_installer_main(
            monkeypatch,
            "rollback",
            "--apply",
            "--root",
            str(tmp_path),
            "--revision",
            revision,
        )
        == 0
    )
    assert calls == [(retained, tmp_path, revision)]


def test_install_rejects_invalid_asset_revision_without_mutation(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    installer.render(staged)
    root = tmp_path / "root"

    with pytest.raises(ValueError, match="asset revision"):
        installer.install(staged, root, "../escape")

    assert not root.exists()


def test_units_are_bounded_persistent_hardened_and_never_implicitly_activated() -> None:
    service = (ROOT / "scripts/systemd/dspace-chat-synthetic.service").read_text()
    timer = (ROOT / "scripts/systemd/dspace-chat-synthetic.timer").read_text()
    install = (ROOT / "scripts/install_dspace_chat_synthetic.py").read_text()
    assert "Type=oneshot" in service and "TimeoutStartSec=300" in service
    assert "RuntimeDirectory=sugarkube/dspace-chat-synthetic" in service
    assert "RuntimeDirectoryMode=0710" in service and "Group=pi" in service
    assert "ProtectSystem=strict" in service and "Persistent=true" in timer
    for mutation in (
        "systemctl enable",
        "systemctl start",
        "systemctl stop",
        "systemctl restart",
        "systemctl disable",
    ):
        assert mutation not in install


def test_lifecycle_is_single_shot_owner_scoped_bounded_and_redacted() -> None:
    source = (ROOT / "scripts/dspace_chat_synthetic_runtime.py").read_text()
    assert "LOCK_NB" in source and "INVOCATION_ID" in source
    assert 'f"uid-{account.pw_uid}-{invocation}"' in source
    assert 'timeout=config["timeoutSeconds"]' in source
    assert "cleanup_invocation(invocation_dir)" in source
    assert "entry.is_dir(follow_symlinks=False)" in source and "invocation_dir.rmdir()" in source
    assert "glob(" not in source and "rmtree" not in source
    for forbidden in ("retry", "systemctl", "rollback", "restart"):
        assert forbidden not in source.lower()
