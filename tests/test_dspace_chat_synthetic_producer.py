"""Deterministic, host-isolated tests for the repository-owned synthetic producer."""

from __future__ import annotations

import copy
import json
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

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
    for key in ("identityContract", "providerConfigContract", "browserContract"):
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


@pytest.mark.parametrize(
    "browser_contract",
    [
        None,
        {"name": runtime.RUNNER_LOCAL, "unexpected": "field"},
        {"name": runtime.SYSTEM_CHROMIUM},
        dict(
            json.loads(CONFIG.read_text())["browserContract"],
            architecture="unsupported",
        ),
    ],
)
def test_configuration_rejects_malformed_browser_contracts(
    tmp_path: Path, browser_contract: object
) -> None:
    path = tmp_path / "config.json"
    value = config(tmp_path)
    value["browserContract"] = browser_contract
    path.write_text(json.dumps(value))

    with pytest.raises(runtime.Invalid, match="browser contract"):
        runtime.load_config(path)


def system_browser_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, Path]:
    root = tmp_path / "target"
    launcher = root / "usr/bin/chromium"
    executable = root / "usr/lib/chromium/chromium"
    for path, contents in ((launcher, b"launcher"), (executable, b"executable")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        path.chmod(0o755)
    info = launcher.stat()
    contract = {
        "name": runtime.SYSTEM_CHROMIUM,
        "architecture": "aarch64",
        "launcherPath": "/usr/bin/chromium",
        "launcherRealpath": "/usr/bin/chromium",
        "launcherSha256": runtime.sha256(launcher),
        "executablePath": "/usr/lib/chromium/chromium",
        "executableRealpath": "/usr/lib/chromium/chromium",
        "executableSha256": runtime.sha256(executable),
        "owner": runtime.pwd.getpwuid(info.st_uid).pw_name,
        "group": runtime.grp.getgrgid(info.st_gid).gr_name,
        "mode": "0755",
        "launcherExecutableRelationship": "distinct-files",
    }
    monkeypatch.setattr(runtime.platform, "machine", lambda: "aarch64")
    return contract, root


def test_explicit_system_browser_contract_validates_target_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract, root = system_browser_fixture(tmp_path, monkeypatch)
    value = {"browserContract": contract}
    provenance = runtime.validate_browser_contract(value, tmp_path / "runner", root)
    assert provenance["executablePath"] == "/usr/lib/chromium/chromium"
    assert provenance["executableSha256"] == contract["executableSha256"]


def test_system_browser_contract_resolves_relative_root_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract, root = system_browser_fixture(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)

    relative = runtime.validate_browser_contract(
        {"browserContract": contract}, tmp_path / "runner", Path(root.name)
    )
    absolute = runtime.validate_browser_contract(
        {"browserContract": contract}, tmp_path / "runner", root.resolve()
    )

    assert relative == absolute


def test_root_normalization_rejects_symlink_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)

    monkeypatch.chdir(tmp_path)
    assert runtime.normalize_root(Path(real.name)) == real
    assert runtime.normalize_root(real) == real
    with pytest.raises(runtime.Invalid, match="source root"):
        runtime.normalize_root(alias)


@pytest.mark.parametrize("coordinate", ["relative/path", "/usr/../outside"])
def test_rooted_coordinates_reject_relative_and_traversal(coordinate: str) -> None:
    with pytest.raises(runtime.Invalid, match="rooted coordinate"):
        runtime._rooted(Path("/private"), coordinate)
    with pytest.raises(ValueError, match="rooted coordinate"):
        installer.rooted(Path("/private"), coordinate)


def test_browser_contract_rejects_missing_source_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract, _root = system_browser_fixture(tmp_path, monkeypatch)

    with pytest.raises(runtime.Invalid, match="source root"):
        runtime.validate_browser_contract(
            {"browserContract": contract}, tmp_path / "runner", tmp_path / "missing"
        )


def test_runner_local_browser_contract_reports_discovered_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = tmp_path / "runner"
    executable = runner / "playwright-browser/chromium/chrome"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"browser")
    monkeypatch.setattr(runtime, "discover_playwright_browser", lambda _runner: executable)

    assert runtime.validate_browser_contract(
        {"browserContract": {"name": runtime.RUNNER_LOCAL}}, runner
    ) == {
        "name": runtime.RUNNER_LOCAL,
        "architecture": platform.machine(),
        "executablePath": "playwright-browser/chromium/chrome",
        "executableSha256": runtime.sha256(executable),
    }


@pytest.mark.parametrize(
    ("prefix", "fault"),
    [
        ("launcher", "missing-path"),
        ("launcher", "wrong-path"),
        ("executable", "missing-path"),
        ("executable", "wrong-path"),
        ("executable", "directory"),
        ("executable", "symlink"),
        ("executable", "non-executable"),
    ],
)
def test_system_browser_contract_rejects_exact_path_and_executable_faults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prefix: str,
    fault: str,
) -> None:
    contract, root = system_browser_fixture(tmp_path, monkeypatch)
    path = root / contract[f"{prefix}Path"].removeprefix("/")
    if fault == "missing-path":
        contract[f"{prefix}Path"] = f"/missing/{prefix}"
    elif fault == "wrong-path":
        wrong = root / f"wrong/{prefix}"
        wrong.parent.mkdir()
        wrong.write_bytes(path.read_bytes())
        wrong.chmod(0o755)
        contract[f"{prefix}Path"] = f"/wrong/{prefix}"
    elif fault == "directory":
        path.unlink()
        path.mkdir()
    elif fault == "symlink":
        path.unlink()
        path.symlink_to(root / "usr/bin/chromium")
    else:
        path.chmod(0o644)
        contract["mode"] = "0644"  # isolate the executable-bit requirement

    with pytest.raises(runtime.Invalid, match="system browser provenance"):
        runtime.validate_browser_contract({"browserContract": contract}, tmp_path / "runner", root)


def test_browser_contracts_never_fallback_to_the_other_direction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract, root = system_browser_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        runtime,
        "discover_playwright_browser",
        lambda _runner: pytest.fail("system contract fell back to runner-local discovery"),
    )
    runtime.validate_browser_contract(
        {"browserContract": contract}, tmp_path / "missing-runner", root
    )

    monkeypatch.setattr(
        runtime,
        "discover_playwright_browser",
        lambda _runner: (_ for _ in ()).throw(runtime.Invalid("runner bundle missing")),
    )
    with pytest.raises(runtime.Invalid, match="runner bundle missing"):
        runtime.validate_browser_contract(
            {"browserContract": {"name": runtime.RUNNER_LOCAL}},
            tmp_path / "missing-runner",
            root,
        )


@pytest.mark.parametrize(
    ("fault", "field"),
    [
        ("architecture", None),
        ("launcher-hash", "launcherSha256"),
        ("executable-hash", "executableSha256"),
        ("mode", "mode"),
        ("owner", "owner"),
        ("group", "group"),
        ("launcher-realpath", "launcherRealpath"),
        ("executable-realpath", "executableRealpath"),
        ("relationship", "launcherExecutableRelationship"),
    ],
)
def test_system_browser_contract_fails_closed_on_provenance_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str, field: str | None
) -> None:
    contract, root = system_browser_fixture(tmp_path, monkeypatch)
    if fault == "architecture":
        monkeypatch.setattr(runtime.platform, "machine", lambda: "x86_64")
    elif fault in {"launcher-hash", "executable-hash"}:
        contract[field] = "0" * 64
    elif fault == "mode":
        (root / "usr/bin/chromium").chmod(0o700)
    elif fault in {"owner", "group"}:
        contract[field] = "definitely-absent"
    elif fault.endswith("realpath"):
        contract[field] = "/unexpected"
    else:
        contract[field] = "same-file"
    with pytest.raises(runtime.Invalid):
        runtime.validate_browser_contract({"browserContract": contract}, tmp_path / "runner", root)


def test_system_browser_contract_rejects_missing_nonregular_and_symlinked_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract, root = system_browser_fixture(tmp_path, monkeypatch)
    launcher = root / "usr/bin/chromium"
    launcher.unlink()
    launcher.mkdir()
    with pytest.raises(runtime.Invalid):
        runtime.validate_browser_contract({"browserContract": contract}, tmp_path / "runner", root)
    launcher.rmdir()
    launcher.symlink_to(root / "usr/lib/chromium/chromium")
    with pytest.raises(runtime.Invalid):
        runtime.validate_browser_contract({"browserContract": contract}, tmp_path / "runner", root)


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
    value["browserContract"] = {"name": runtime.RUNNER_LOCAL}
    runner = Path(value["runnerRoot"]) / "fixture"
    runner.mkdir(parents=True)
    git("init", cwd=runner)
    git("config", "user.email", "tests@example.invalid", cwd=runner)
    git("config", "user.name", "Tests", cwd=runner)
    required = {
        "scripts/run-remote-chat-smoke.mjs": "// runner\n",
        "scripts/remote-chat-smoke-completion.mjs": "// completion\n",
        "frontend/e2e/remote-chat-smoke.spec.ts": "// smoke\n",
        "frontend/playwright.config.ts": (
            "const chromiumExecutable = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH &&\n"
            "  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH.trim();\n"
            "export default {projects: [{name: 'chromium', use: {launchOptions: {\n"
            "  executablePath: chromiumExecutable || undefined,\n"
            "}}}]};\n"
        ),
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
        "browserContract": value["browserContract"],
        "playwrightBrowserExecutable": "playwright-browser/browser-executable",
        "files": {relative: runtime.sha256(destination / relative) for relative in required},
    }
    manifest["browserProvenance"] = {
        "name": runtime.RUNNER_LOCAL,
        "architecture": platform.machine(),
        "executablePath": "playwright-browser/browser-executable",
        "executableSha256": runtime.sha256(destination / "playwright-browser/browser-executable"),
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


def test_every_runner_git_command_trusts_only_exact_validated_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, runner = runtime_runner(tmp_path)
    real_run = subprocess.run
    git_calls: list[tuple[list[str], dict[str, str]]] = []
    hostile_git_environment = {
        "GIT_COMMON_DIR": str(tmp_path / "common"),
        "GIT_INDEX_FILE": str(tmp_path / "index"),
        "GIT_OBJECT_DIRECTORY": str(tmp_path / "objects"),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(tmp_path / "alternate-objects"),
        "GIT_SHALLOW_FILE": str(tmp_path / "shallow"),
        "GIT_NAMESPACE": "redirected",
        "GIT_DIR": str(tmp_path / "redirected"),
        "GIT_WORK_TREE": str(tmp_path / "redirected-worktree"),
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_VALUE_0": "*",
        "GIT_CONFIG_PARAMETERS": "'safe.directory'='*'",
    }
    for key, hostile_value in hostile_git_environment.items():
        monkeypatch.setenv(key, hostile_value)
    monkeypatch.setenv("SUGARKUBE_TEST_INHERITED", "preserved")

    def inspect(argv, *args, **kwargs):
        if argv[0] == "/usr/bin/node":
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=str(runner / "playwright-browser/browser-executable").encode(),
            )
        git_calls.append((argv, kwargs["env"]))
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(runtime.subprocess, "run", inspect)
    assert runtime.validate_runner(value) == runner.resolve()
    assert len(git_calls) == 4
    for argv, environment in git_calls:
        assert argv[:5] == [
            "git",
            "-c",
            f"safe.directory={runner.resolve()}",
            "-C",
            str(runner.resolve()),
        ]
        assert "safe.directory=*" not in argv
        assert environment["GIT_OPTIONAL_LOCKS"] == "0"
        assert environment["GIT_CONFIG_COUNT"] == "0"
        assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
        assert environment["GIT_CONFIG_GLOBAL"] == os.devnull
        assert environment["SUGARKUBE_TEST_INHERITED"] == "preserved"
        assert set(environment) & set(hostile_git_environment) == {"GIT_CONFIG_COUNT"}


@pytest.mark.parametrize("fault", ["missing", "relative", "parent", "symlink", "mismatch"])
def test_runner_path_is_rejected_before_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    value, runner = runtime_runner(tmp_path)
    if fault == "missing":
        value["runnerRoot"] = str(tmp_path / "missing")
    elif fault == "relative":
        value["runnerRoot"] = "relative/runners"
    elif fault == "parent":
        value["runnerRoot"] = str(tmp_path / "runners" / ".." / "runners")
    elif fault == "symlink":
        link = tmp_path / "linked-runner"
        runner.rename(tmp_path / "real-runner")
        link.symlink_to(tmp_path / "real-runner", target_is_directory=True)
        value["runnerRoot"] = str(tmp_path)
        value["runnerRevision"] = link.name
    else:
        value["runnerRevision"] = "0" * 40

    def reject_git(argv, *args, **kwargs):
        if argv[0] == "git":
            pytest.fail("Git must not execute before runner path validation")
        return subprocess.CompletedProcess(argv, 0, stdout=b"")

    monkeypatch.setattr(runtime.subprocess, "run", reject_git)
    with pytest.raises((runtime.Invalid, OSError)):
        runtime.validate_runner(value)


@pytest.mark.skipif(os.geteuid() != 0, reason="requires root to drop to an unprivileged uid")
def test_root_owned_runner_validates_as_unprivileged_user_without_mutation(tmp_path: Path) -> None:
    value, runner = runtime_runner(tmp_path)
    nobody = next(entry for entry in __import__("pwd").getpwall() if entry.pw_uid not in {0, 65534})
    group = __import__("grp").getgrgid(nobody.pw_gid)
    tmp_path.chmod(0o755)
    for parent in tmp_path.parents:
        if parent == Path("/tmp"):
            break
        parent.chmod(0o755)
    for path in [tmp_path / "runners", *runner.rglob("*")]:
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() or os.access(path, os.X_OK) else 0o644)
    before = {
        str(path.relative_to(tmp_path)): (
            path.lstat().st_uid,
            path.lstat().st_gid,
            path.lstat().st_mode,
        )
        for path in [tmp_path, *tmp_path.rglob("*")]
    }
    config_path = tmp_path / "runtime-config.json"
    config_path.write_text(json.dumps(value))
    config_path.chmod(0o644)
    browser_path = str(runner / "playwright-browser/browser-executable")
    code = (
        "import json, subprocess; from pathlib import Path; "
        "from scripts import dspace_chat_synthetic_runtime as r; "
        f"c=json.loads(Path({str(config_path)!r}).read_text()); "
        "real_run=subprocess.run; "
        "r.subprocess.run=lambda argv,*a,**kw: subprocess.CompletedProcess("
        f"argv,0,stdout={browser_path!r}.encode()) if argv[0]=='/usr/bin/node' "
        "else real_run(argv,*a,**kw); "
        "print(r.validate_runner(c))"
    )
    completed = subprocess.run(
        ["/usr/bin/python3", "-c", code],
        cwd=ROOT,
        env={**os.environ, "HOME": str(tmp_path / "unwritable-home")},
        capture_output=True,
        text=True,
        preexec_fn=lambda: (os.setgid(group.gr_gid), os.setuid(nobody.pw_uid)),
        check=False,
    )
    assert completed.returncode == 0, completed.stdout
    assert completed.stderr == ""
    assert completed.stdout.strip() == str(runner.resolve())
    after = {
        str(path.relative_to(tmp_path)): (
            path.lstat().st_uid,
            path.lstat().st_gid,
            path.lstat().st_mode,
        )
        for path in [tmp_path, *tmp_path.rglob("*")]
        if path != config_path
    }
    assert {key: value for key, value in before.items() if key != "runtime-config.json"} == after


def refresh_tracked_stat(runner: Path) -> None:
    """Make Git reconsider a tracked file without changing its bytes."""
    tracked = runner / "package.json"
    info = tracked.stat()
    os.utime(tracked, ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000))


def test_git_optional_locks_keep_validation_index_metadata_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, runner = runtime_runner(tmp_path)
    index = runner / ".git/index"
    index.chmod(0o640)
    refresh_tracked_stat(runner)
    previous_umask = os.umask(0o077)
    try:
        git("status", "--porcelain", "--untracked-files=no", cwd=runner)
    finally:
        os.umask(previous_umask)
    assert stat.S_IMODE(index.stat().st_mode) == 0o600

    index.chmod(0o640)
    refresh_tracked_stat(runner)
    real_run = subprocess.run
    monkeypatch.setenv("SUGARKUBE_TEST_INHERITED", "preserved")

    def fake_node(argv, *args, **kwargs):
        if argv[0] == "/usr/bin/node":
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=str(runner / "playwright-browser/browser-executable").encode(),
            )
        assert kwargs["env"]["GIT_OPTIONAL_LOCKS"] == "0"
        assert kwargs["env"]["SUGARKUBE_TEST_INHERITED"] == "preserved"
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(runtime.subprocess, "run", fake_node)
    previous_umask = os.umask(0o077)
    try:
        assert runtime.validate_runner(value) == runner
    finally:
        os.umask(previous_umask)
    assert stat.S_IMODE(index.stat().st_mode) == 0o640


def test_runner_validation_still_rejects_dirty_tracked_content_without_optional_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, runner = runtime_runner(tmp_path)
    (runner / "package.json").write_text('{"dirty":true}\n')
    real_run = subprocess.run

    def fake_node(argv, *args, **kwargs):
        if argv[0] == "/usr/bin/node":
            pytest.fail("dirty tracked state must fail before browser discovery")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(runtime.subprocess, "run", fake_node)
    with pytest.raises(runtime.Invalid, match="runner tracked state"):
        runtime.validate_runner(value)


def test_alternate_index_cannot_hide_dirty_real_runner_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, runner = runtime_runner(tmp_path)
    alternate_index = tmp_path / "clean-index"
    subprocess.run(
        ["git", "read-tree", "HEAD"],
        cwd=runner,
        env={**os.environ, "GIT_INDEX_FILE": str(alternate_index)},
        check=True,
    )
    tracked = runner / "package.json"
    original = tracked.read_bytes()
    tracked.write_bytes(b'{"dirty":true}\n')
    git("add", "package.json", cwd=runner)
    tracked.write_bytes(original)
    monkeypatch.setenv("GIT_INDEX_FILE", str(alternate_index))

    with pytest.raises(runtime.Invalid, match="runner tracked state"):
        runtime.validate_runner(value)


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
        lambda *_args, **_kwargs: {
            "name": runtime.RUNNER_LOCAL,
            "architecture": platform.machine(),
            "executablePath": "playwright-browser/browser-executable",
            "executableSha256": "0" * 64,
        },
    )
    (runner / "sugarkube-runner-manifest.json").write_text(
        json.dumps(
            {
                "browserProvenance": runtime.validate_browser_contract(value, runner),
            }
        )
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


def test_runtime_plumbs_exact_system_executable_and_not_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, _metric, _sibling, calls = prepare_runtime_run(tmp_path, monkeypatch)
    provenance = {
        "name": runtime.SYSTEM_CHROMIUM,
        "architecture": "aarch64",
        "executablePath": "/usr/lib/chromium/chromium",
        "executableSha256": "f" * 64,
    }
    runner = tmp_path / "runner"
    (runner / "sugarkube-runner-manifest.json").write_text(
        json.dumps({"browserProvenance": provenance})
    )
    monkeypatch.setattr(runtime, "validate_browser_contract", lambda *_a, **_k: provenance)

    assert runtime.run(value) == 0
    child = next(call for call in calls if call["argv"][0] == "runuser")
    assert child["env"]["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"] == provenance["executablePath"]
    assert "PLAYWRIGHT_BROWSERS_PATH" not in child["env"]


def test_runtime_browser_drift_blocks_playwright_and_preserves_metric(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, metric, _sibling, calls = prepare_runtime_run(tmp_path, monkeypatch)
    provenance = runtime.validate_browser_contract(value, tmp_path / "runner")
    validations = 0

    def drift(*_args, **_kwargs):
        nonlocal validations
        validations += 1
        if validations == 1:
            return provenance
        raise runtime.Invalid("system browser provenance")

    monkeypatch.setattr(runtime, "validate_browser_contract", drift)
    assert runtime.run(value) == 1
    assert metric.read_bytes() == b"previous metric\n"
    assert not any(call["argv"][0] == "runuser" for call in calls)


@pytest.mark.parametrize(
    ("diagnostic", "status", "expected"),
    [
        (b"browserType.launch: Failed to launch chromium", 1, "browser-executable-launch-failure"),
        (b"playwright.config.ts: Cannot find module", 1, "playwright-configuration-failure"),
        (
            b"journey completion was not confirmed; result preserved",
            1,
            "test-failure-before-completion-publication",
        ),
        (b"result publication failed", 1, "completion-publisher-failure"),
        (b"unrecognized and private", 0, "missing-current-result-after-child-success"),
        (b"unrecognized and private", 1, "missing-current-result-after-child-failure"),
    ],
)
def test_missing_result_classification_is_allowlisted_and_bounded(
    diagnostic: bytes, status: int, expected: str
) -> None:
    secret_prefix = b"credential=must-not-escape\n" * (runtime.MAX_CHILD_DIAGNOSTIC_BYTES + 1)
    assert runtime.classify_missing_result(status, secret_prefix + diagnostic) == expected


def test_browser_launch_failure_preserves_metric_and_prints_only_classification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value, metric, _sibling, _calls = prepare_runtime_run(tmp_path, monkeypatch, "missing")
    real_fake = runtime.subprocess.run

    def classified_run(argv, **kwargs):
        completed = real_fake(argv, **kwargs)
        if argv[0] == "runuser":
            completed.stderr = b"credential=must-not-escape\nbrowserType.launch: Failed to launch"
            completed.returncode = 1
        return completed

    monkeypatch.setattr(runtime.subprocess, "run", classified_run)
    assert runtime.run(value) == 1
    output = capsys.readouterr().out
    assert "reason=current-result-missing" in output
    assert "classification=browser-executable-launch-failure" in output
    assert "child_status=1" in output
    assert "credential" not in output
    assert metric.read_bytes() == b"previous metric\n"
    assert not (Path(value["resultRoot"]) / f"uid-{os.getuid()}-{'a' * 32}").exists()


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
        {"name": runtime.RUNNER_LOCAL},
        Path("/"),
    )
    manifest = json.loads((output / "sugarkube-runner-manifest.json").read_text())
    relative = manifest["playwrightBrowserExecutable"]
    assert relative == "playwright-browser/chromium/chrome"
    assert manifest["files"][relative] == runtime.sha256(output / relative)

    __import__("shutil").rmtree(source)
    __import__("shutil").rmtree(browser_bundle)
    value = config(tmp_path)
    value.update(runnerRoot=str(output.parent), runnerRevision=revision)
    value["browserContract"] = {"name": runtime.RUNNER_LOCAL}
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
        RUNNER_LOCAL = runtime.RUNNER_LOCAL
        SYSTEM_CHROMIUM = runtime.SYSTEM_CHROMIUM

        normalize_root = staticmethod(runtime.normalize_root)

        @staticmethod
        def discover_playwright_browser(runner: Path) -> Path:
            return runner / discovered

        @staticmethod
        def validate_browser_contract(_config: dict, runner: Path, _root: Path) -> dict:
            browser = runner / discovered
            return {
                "name": runtime.RUNNER_LOCAL,
                "architecture": platform.machine(),
                "executablePath": str(discovered),
                "executableSha256": runtime.sha256(browser),
            }

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
        {"name": runtime.RUNNER_LOCAL},
        Path("/"),
    )

    manifest = json.loads((output / "sugarkube-runner-manifest.json").read_text())
    assert manifest["playwrightBrowserExecutable"] == str(discovered)
    assert manifest["files"][str(discovered)] == runtime.sha256(output / discovered)
    assert validations[-1] == (output, revision)


def test_system_materialize_skips_browser_bundle_and_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, revision, _browser_bundle, pnpm = materialization_fixture(tmp_path)
    contract, browser_root = system_browser_fixture(tmp_path, monkeypatch)
    output = tmp_path / "output" / revision
    environments = []
    real_run = installer.subprocess.run

    def record_run(argv, **kwargs):
        if argv[0] == str(pnpm) and argv[1] == "install":
            environments.append(kwargs["env"])
        return real_run(argv, **kwargs)

    monkeypatch.setattr(installer.subprocess, "run", record_run)
    installer.materialize(
        source,
        revision,
        runtime.APPROVED_REPOSITORY_IDENTITY,
        output,
        str(pnpm),
        "9.1.0",
        None,
        contract,
        browser_root,
    )
    manifest = json.loads((output / "sugarkube-runner-manifest.json").read_text())
    assert manifest["playwrightBrowserExecutable"] is None
    assert manifest["browserContract"] == contract
    assert not (output / "playwright-browser").exists()
    assert environments[0]["PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"] == "1"
    assert "PLAYWRIGHT_BROWSERS_PATH" not in environments[0]

    with pytest.raises(ValueError, match="forbids"):
        installer.materialize(
            source,
            revision,
            runtime.APPROVED_REPOSITORY_IDENTITY,
            tmp_path / "another-output",
            str(pnpm),
            "9.1.0",
            tmp_path,
            contract,
            browser_root,
        )


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
            "--browser-source-root",
            "/",
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
            json.loads(CONFIG.read_text())["browserContract"],
            Path("/").resolve(),
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
    RUNNER_LOCAL = runtime.RUNNER_LOCAL
    SYSTEM_CHROMIUM = runtime.SYSTEM_CHROMIUM

    normalize_root = staticmethod(runtime.normalize_root)

    @staticmethod
    def load_config(path: Path) -> dict:
        return json.loads(path.read_text())

    @staticmethod
    def validate_runner(value: dict) -> Path:
        runner = Path(value["runnerRoot"]) / value["runnerRevision"]
        if (runner / "invalid").exists():
            raise ValueError("runner validation failed")
        return runner

    @staticmethod
    def validate_browser_contract(_value: dict, runner: Path, _root: Path) -> dict:
        return json.loads((runner / "sugarkube-runner-manifest.json").read_text())[
            "browserProvenance"
        ]


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
                "browserProvenance": {
                    "name": runtime.SYSTEM_CHROMIUM,
                    "architecture": "aarch64",
                    "executablePath": "/usr/lib/chromium/chromium",
                    "executableSha256": (
                        "f8cf8a41a3406375dc9b9af5ce25a3fe" "ceca3d4e9e72d18671db07cdee7a75a6"
                    ),
                    "launcherPath": "/usr/bin/chromium",
                    "launcherRealpath": "/usr/bin/chromium",
                    "launcherSha256": (
                        "be1d239c2a7a9298c202d506e589d230" "56064bd52b82fa3d3cf72a0a2de3337c"
                    ),
                    "executableRealpath": "/usr/lib/chromium/chromium",
                    "owner": "root",
                    "group": "root",
                    "mode": "0755",
                    "launcherExecutableRelationship": "distinct-files",
                },
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


def tree_metadata(root: Path) -> dict[str, tuple[int, int, int]]:
    return {
        str(path.relative_to(root)): (
            path.lstat().st_uid,
            path.lstat().st_gid,
            stat.S_IMODE(path.lstat().st_mode),
        )
        for path in root.rglob("*")
    }


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
    assert "playwrightBrowserExecutable=none" in output
    assert "runnerValidation=passed" in output
    provenance = json.loads((runner / "sugarkube-runner-manifest.json").read_text())[
        "browserProvenance"
    ]
    for key in (
        "architecture",
        "executablePath",
        "executableSha256",
        "launcherPath",
        "launcherSha256",
    ):
        assert str(provenance[key]) in output
    assert "browserContract=system-chromium-v1" in output
    assert "credential" not in output.lower()
    assert "rawResult" not in output
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


def test_system_browser_preflight_precedes_all_installer_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class RejectingRuntime:
        SYSTEM_CHROMIUM = runtime.SYSTEM_CHROMIUM

        normalize_root = staticmethod(runtime.normalize_root)

        @staticmethod
        def load_config(_path: Path) -> dict:
            return {"browserContract": {"name": runtime.SYSTEM_CHROMIUM}}

        @staticmethod
        def validate_browser_contract(*_args) -> dict:
            raise runtime.Invalid("browser preflight")

    monkeypatch.chdir(tmp_path)
    (tmp_path / "rehearsal-root").mkdir()
    monkeypatch.setattr(installer, "runtime_module", lambda: RejectingRuntime())
    monkeypatch.setattr(installer, "render", lambda _path: pytest.fail("render mutated output"))

    with pytest.raises(runtime.Invalid, match="browser preflight"):
        run_installer_main(
            monkeypatch,
            "apply",
            "--root",
            "rehearsal-root",
            "--runner-snapshot",
            "snapshot",
        )

    assert not any((tmp_path / "rehearsal-root").iterdir())


@pytest.mark.parametrize("operation", ["status", "dry-run", "apply", "rollback"])
def test_installer_rejects_symlink_root_before_probe_or_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(installer, "status", lambda _root: pytest.fail("status probed"))
    monkeypatch.setattr(installer, "render", lambda _root: pytest.fail("render mutated"))
    monkeypatch.setattr(installer, "validate", lambda _root: pytest.fail("rollback probed"))

    arguments = [operation, "--root", str(alias)]
    if operation in {"dry-run", "apply"}:
        arguments += ["--runner-snapshot", str(tmp_path / "snapshot")]
    with pytest.raises(Exception, match="source root"):
        run_installer_main(monkeypatch, *arguments)
    assert not any(real.iterdir())


def test_materialize_rejects_symlink_browser_root_before_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "browser-root"
    real.mkdir()
    alias = tmp_path / "browser-alias"
    alias.symlink_to(real, target_is_directory=True)
    output = tmp_path / "output"
    monkeypatch.setattr(
        installer, "verify_source", lambda *_args: pytest.fail("source validation started")
    )

    with pytest.raises(Exception, match="source root"):
        installer.materialize(
            tmp_path / "source",
            "0" * 40,
            "identity",
            output,
            "pnpm",
            "1.0",
            None,
            {"name": runtime.SYSTEM_CHROMIUM},
            alias,
        )
    assert not output.exists()


def test_explicit_live_root_reaches_status_only_after_mocked_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = []
    monkeypatch.setattr(runtime, "normalize_root", lambda root: seen.append(root) or Path("/"))
    monkeypatch.setattr(installer, "runtime_module", lambda: runtime)
    monkeypatch.setattr(installer, "status", lambda root: seen.append(root) or 0)

    assert run_installer_main(monkeypatch, "status", "--root", "/") == 0
    assert seen == [Path("/"), Path("/")]


def runner_snapshot_fixture(tmp_path: Path) -> tuple[Path, str]:
    revision = "97ab09f13fb098de928a878bf1fe9b8d13032cb5"
    snapshot = tmp_path / "source" / revision
    snapshot.mkdir(parents=True)
    (snapshot / ".git").mkdir()
    (snapshot / "dependency.ok").write_text("complete\n")
    (snapshot / "sugarkube-runner-manifest.json").write_text(
        json.dumps({"browserProvenance": {"name": runtime.SYSTEM_CHROMIUM}})
    )
    return snapshot, revision


class FakeSnapshotRuntime:
    RUNNER_LOCAL = runtime.RUNNER_LOCAL
    SYSTEM_CHROMIUM = runtime.SYSTEM_CHROMIUM

    def __init__(self, fail_copy: bool = False):
        self.fail_copy = fail_copy
        self.validated = []

    normalize_root = staticmethod(runtime.normalize_root)

    @staticmethod
    def load_config(path: Path) -> dict:
        return json.loads(path.read_text())

    def validate_runner(self, config: dict) -> Path:
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

    @staticmethod
    def validate_browser_contract(_config: dict, _runner: Path, _root: Path) -> dict:
        return {"name": runtime.SYSTEM_CHROMIUM}


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
    root.mkdir()
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


def test_runner_install_normalizes_private_source_without_changing_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revision = "97ab09f13fb098de928a878bf1fe9b8d13032cb5"
    snapshot = tmp_path / "source" / revision
    previous_umask = os.umask(0o077)
    try:
        snapshot.mkdir(parents=True)
        git("init", cwd=snapshot)
        git("config", "user.email", "tests@example.invalid", cwd=snapshot)
        git("config", "user.name", "Tests", cwd=snapshot)
        for relative in installer.CRITICAL:
            path = snapshot / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"fixture:{relative}\n")
        (snapshot / "dependency.ok").write_text("complete\n")
        pnpm_package = snapshot / "node_modules/.pnpm/example"
        pnpm_package.mkdir(parents=True)
        (pnpm_package / "index.js").write_text("export default true;\n")
        playwright = snapshot / "frontend/node_modules/playwright-core/cli.sh"
        playwright.parent.mkdir(parents=True)
        playwright.write_bytes(b"#!/bin/sh\nexit 0\n")
        playwright.chmod(0o700)
        playwright_link = snapshot / "frontend/node_modules/.bin/playwright"
        playwright_link.parent.mkdir(parents=True)
        playwright_link.symlink_to("../playwright-core/cli.sh")
        dependency_link = snapshot / "frontend/node_modules/example"
        dependency_link.symlink_to("../../node_modules/.pnpm/example")
        git("add", ".", cwd=snapshot)
        git("commit", "-m", "private fixture", cwd=snapshot)
        head = git("rev-parse", "HEAD", cwd=snapshot)
        critical_hashes = {
            relative: installer.sha(snapshot / relative) for relative in installer.CRITICAL
        }
        (snapshot / "sugarkube-runner-manifest.json").write_text(
            json.dumps(
                {
                    "browserProvenance": {"name": runtime.SYSTEM_CHROMIUM},
                    "files": critical_hashes,
                }
            )
        )
    finally:
        os.umask(previous_umask)
    script = playwright
    before = tree_bytes(snapshot)
    manifest_sha = installer.sha(snapshot / "sugarkube-runner-manifest.json")
    link_text = {
        str(path.relative_to(snapshot)): os.readlink(path)
        for path in snapshot.rglob("*")
        if path.is_symlink()
    }
    staged = tmp_path / "staged"
    installer.render(staged)
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(installer, "runtime_module", lambda: FakeSnapshotRuntime())

    installed, created = installer.install_runner(staged, snapshot, root)

    assert created and installed.name == revision
    assert tree_bytes(installed) == before
    assert stat.S_IMODE(script.stat().st_mode) == 0o700  # source remains private
    assert stat.S_IMODE((installed / script.relative_to(snapshot)).stat().st_mode) == 0o750
    assert stat.S_IMODE((installed / "package.json").stat().st_mode) == 0o640
    assert {
        str(path.relative_to(installed)): os.readlink(path)
        for path in installed.rglob("*")
        if path.is_symlink()
    } == link_text
    assert git("rev-parse", "HEAD", cwd=installed) == head
    git("fsck", "--full", cwd=installed)
    assert all(
        installer.sha(installed / path) == expected for path, expected in critical_hashes.items()
    )
    assert installer.sha(installed / "sugarkube-runner-manifest.json") == manifest_sha
    assert (installed / "node_modules/.pnpm/example/index.js").is_file()
    assert (installed / "frontend/node_modules/example/index.js").is_file()
    resolved_playwright = installed / "frontend/node_modules/.bin/playwright"
    assert (
        resolved_playwright.resolve() == installed / "frontend/node_modules/playwright-core/cli.sh"
    )
    assert os.access(resolved_playwright, os.X_OK)
    for parent in (root / "var/lib/sugarkube", installed.parent):
        assert stat.S_IMODE(parent.stat().st_mode) == 0o710
        assert parent.stat().st_gid == os.getgid()
    assert stat.S_IMODE(installed.stat().st_mode) == 0o750
    assert installed.stat().st_gid == os.getgid()
    for path in [installed, *installed.rglob("*")]:
        if not path.is_symlink():
            assert not stat.S_IMODE(path.stat().st_mode) & 0o022
    config_value = json.loads((staged / "etc/sugarkube/dspace-chat-synthetic.json").read_text())
    installer.validate_runner_access(config_value, installed, root)
    installer.validate_runner(installed, head)


@pytest.mark.parametrize("kind", ["executable", "symlink-target"])
def test_child_access_validation_rejects_inaccessible_required_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    snapshot, _ = runner_snapshot_fixture(tmp_path)
    executable = snapshot / "shim"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o700)
    (snapshot / "shim-link").symlink_to("shim")
    staged = tmp_path / "staged"
    installer.render(staged)
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(installer, "runtime_module", lambda: FakeSnapshotRuntime())
    runner, _ = installer.install_runner(staged, snapshot, root)
    inaccessible = runner / ("shim" if kind == "executable" else "dependency.ok")
    if kind == "symlink-target":
        (runner / "shim-link").unlink()
        (runner / "shim-link").symlink_to("dependency.ok")
    inaccessible.chmod(0o600)
    value = json.loads((staged / "etc/sugarkube/dspace-chat-synthetic.json").read_text())

    with pytest.raises(ValueError, match="access metadata|cannot access"):
        installer.validate_runner_access(value, runner, root)


def test_child_access_validation_rejects_parent_and_file_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, _ = runner_snapshot_fixture(tmp_path)
    executable = snapshot / "shim"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    staged = tmp_path / "staged"
    installer.render(staged)
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(installer, "runtime_module", lambda: FakeSnapshotRuntime())
    runner, _ = installer.install_runner(staged, snapshot, root)
    value = json.loads((staged / "etc/sugarkube/dspace-chat-synthetic.json").read_text())
    for path, mode in (
        (root / "var/lib/sugarkube", 0o700),
        (runner / "dependency.ok", 0o600),
    ):
        original = stat.S_IMODE(path.stat().st_mode)
        path.chmod(mode)
        with pytest.raises(ValueError, match="access metadata|cannot access"):
            installer.validate_runner_access(value, runner, root)
        path.chmod(original)


def test_runner_access_paths_rejects_parent_outside_application_tree(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = root / "etc"
    outside.mkdir()
    before = outside.stat()

    with pytest.raises(ValueError, match="within /var/lib/sugarkube"):
        installer.runner_access_paths(root, outside)

    after = outside.stat()
    assert (after.st_uid, after.st_gid, after.st_mode) == (
        before.st_uid,
        before.st_gid,
        before.st_mode,
    )


def test_child_access_validation_rejects_unsupported_file_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, _ = runner_snapshot_fixture(tmp_path)
    staged = tmp_path / "staged"
    installer.render(staged)
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(installer, "runtime_module", lambda: FakeSnapshotRuntime())
    runner, _ = installer.install_runner(staged, snapshot, root)
    fifo = runner / "unexpected.fifo"
    os.mkfifo(fifo, 0o640)
    os.chown(fifo, os.getuid(), os.getgid())
    value = json.loads((staged / "etc/sugarkube/dspace-chat-synthetic.json").read_text())

    with pytest.raises(ValueError, match="unsupported file type"):
        installer.validate_runner_access(value, runner, root)


def test_non_executable_shebang_file_only_requires_read_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, _ = runner_snapshot_fixture(tmp_path)
    data = snapshot / "script-data"
    data.write_text("#!/bin/sh\nnot executed\n")
    data.chmod(0o600)
    staged = tmp_path / "staged"
    installer.render(staged)
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(installer, "runtime_module", lambda: FakeSnapshotRuntime())

    runner, _ = installer.install_runner(staged, snapshot, root)

    assert stat.S_IMODE((runner / data.name).stat().st_mode) == 0o640


def test_service_identity_rejects_account_with_different_primary_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import grp
    import pwd

    monkeypatch.setattr(pwd, "getpwnam", lambda _name: SimpleNamespace(pw_uid=1234, pw_gid=2345))
    monkeypatch.setattr(grp, "getgrnam", lambda _name: SimpleNamespace(gr_gid=3456))

    with pytest.raises(ValueError, match="primary group does not match"):
        installer.service_identity(
            {"serviceAccount": "synthetic", "serviceGroup": "synthetic"}, Path("/")
        )


def test_service_identity_rejects_unavailable_live_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pwd

    monkeypatch.setattr(pwd, "getpwnam", lambda _name: (_ for _ in ()).throw(KeyError()))

    with pytest.raises(ValueError, match="identity is unavailable"):
        installer.service_identity(
            {"serviceAccount": "absent", "serviceGroup": "absent"}, Path("/")
        )


def test_service_identity_accepts_matching_live_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import grp
    import pwd

    monkeypatch.setattr(pwd, "getpwnam", lambda _name: SimpleNamespace(pw_uid=1234, pw_gid=2345))
    monkeypatch.setattr(grp, "getgrnam", lambda _name: SimpleNamespace(gr_gid=2345))

    assert installer.service_identity(
        {"serviceAccount": "synthetic", "serviceGroup": "synthetic"}, Path("/")
    ) == (1234, 2345)


@pytest.mark.parametrize("fault", ["invalid-parent", "missing", "config-bytes"])
def test_live_asset_validation_rejects_invalid_active_tree(tmp_path: Path, fault: str) -> None:
    root = tmp_path / "root"
    retained = tmp_path / "retained"
    relative = Path("etc/sugarkube/dspace-chat-synthetic.json")
    retained_config = retained / relative
    retained_config.parent.mkdir(parents=True)
    retained_config.write_bytes(b"retained config\n")
    live_config = root / relative
    live_config.parent.mkdir(parents=True)
    live_config.write_bytes(retained_config.read_bytes())
    manifest = {str(relative): installer.sha(retained_config)}

    if fault == "invalid-parent":
        live_config.unlink()
        (root / "etc/sugarkube").rmdir()
        (root / "etc/sugarkube").write_text("not a directory\n")
        match = "invalid directory"
    elif fault == "missing":
        live_config.unlink()
        match = "missing or invalid"
    else:
        live_config.write_bytes(b"different config bytes\n")
        manifest[str(relative)] = installer.sha(live_config)
        match = "configuration does not match"

    with pytest.raises(ValueError, match=match):
        installer.validate_live_assets(root, retained, manifest)


@pytest.mark.parametrize("fault", ["dangling", "escaping"])
def test_runner_access_rejects_unsafe_symlink_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    root, runner, _revision, _manifest_sha = access_repair_fixture(tmp_path, monkeypatch)
    link = runner / "dependency-link"
    link.symlink_to("missing" if fault == "dangling" else tmp_path / "outside")
    before = tree_bytes(root)

    with pytest.raises(ValueError, match="missing or escapes"):
        installer.runner_access_plan(
            json.loads((root / "etc/sugarkube/dspace-chat-synthetic.json").read_text()),
            runner,
            root,
        )

    assert tree_bytes(root) == before


def access_repair_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, str, str]:
    root = tmp_path / "root"
    root.mkdir()
    retained = root / "var/lib/sugarkube/dspace-chat-installations" / ("6" * 64)
    installer.render(retained)
    installer.activate(retained, root, retained.name)
    snapshot, revision = runner_snapshot_fixture(tmp_path)
    runner = root / "var/lib/sugarkube/dspace-chat-runners" / revision
    __import__("shutil").copytree(snapshot, runner, symlinks=True)
    for path in [runner.parent.parent, runner.parent, runner, *runner.rglob("*")]:
        if not path.is_symlink():
            path.chmod(0o700 if path.is_dir() else 0o600)
    monkeypatch.setattr(installer, "runtime_module", lambda: FakeSnapshotRuntime())
    return root, runner, revision, installer.sha(runner / "sugarkube-runner-manifest.json")


class PlannedPath:
    def __init__(self, uid: int, gid: int, mode: int) -> None:
        self.info = SimpleNamespace(st_uid=uid, st_gid=gid, st_mode=mode)
        self.chmods: list[int] = []

    def lstat(self):
        return self.info

    def chmod(self, mode: int) -> None:
        self.chmods.append(mode)


@pytest.mark.parametrize(
    ("actual", "desired", "mode", "follow", "expected_chowns", "expected_chmods"),
    [
        ((10, 20, 0o100640), (10, 20), 0o640, True, 0, 0),
        ((10, 20, 0o040750), (10, 20), 0o750, True, 0, 0),
        ((10, 20, 0o100600), (10, 20), 0o640, True, 0, 1),
        ((10, 30, 0o100640), (10, 20), 0o640, True, 1, 0),
        ((30, 30, 0o100600), (10, 20), 0o640, True, 1, 1),
        ((10, 20, 0o120777), (10, 20), None, False, 0, 0),
        ((30, 20, 0o120777), (10, 20), None, False, 1, 0),
    ],
)
def test_apply_runner_access_plan_writes_only_mismatched_fields(
    monkeypatch: pytest.MonkeyPatch,
    actual: tuple[int, int, int],
    desired: tuple[int, int],
    mode: int | None,
    follow: bool,
    expected_chowns: int,
    expected_chmods: int,
) -> None:
    path = PlannedPath(*actual)
    chowns = []
    monkeypatch.setattr(
        installer.os, "chown", lambda *args, **kwargs: chowns.append((args, kwargs))
    )

    installer.apply_runner_access_plan([(path, *desired, mode, follow)])

    assert len(chowns) == expected_chowns
    assert path.chmods == ([mode] if expected_chmods else [])
    if chowns:
        assert chowns == [((path, *desired), {"follow_symlinks": follow})]
    if mode is None:
        assert path.chmods == []


def test_apply_runner_access_plan_large_plan_scales_with_mismatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact = [PlannedPath(10, 20, 0o100640) for _ in range(2048)]
    mismatch = PlannedPath(30, 30, 0o100600)
    chowns = []
    monkeypatch.setattr(
        installer.os, "chown", lambda *args, **kwargs: chowns.append((args, kwargs))
    )
    plan = [(path, 10, 20, 0o640, True) for path in [*exact, mismatch]]

    installer.apply_runner_access_plan(plan)

    assert len(chowns) == 1
    assert sum(len(path.chmods) for path in [*exact, mismatch]) == 1
    assert all(not path.chmods for path in exact)
    assert chowns == [((mismatch, 10, 20), {"follow_symlinks": True})]
    assert mismatch.chmods == [0o640]


def test_apply_runner_access_plan_fails_without_retry_or_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = PlannedPath(30, 20, 0o100640)
    calls = 0

    def fail(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise PermissionError("denied")

    monkeypatch.setattr(installer.os, "chown", fail)

    with pytest.raises(PermissionError, match="denied"):
        installer.apply_runner_access_plan([(path, 10, 20, 0o640, True)])
    assert calls == 1
    assert path.chmods == []


def test_access_repair_report_only_and_explicit_apply_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    root, runner, revision, manifest_sha = access_repair_fixture(tmp_path, monkeypatch)
    before = tree_bytes(root)
    metadata_before = tree_metadata(root)
    with monkeypatch.context() as report_patch:
        report_patch.setattr(
            installer.os,
            "chown",
            lambda *_args, **_kwargs: pytest.fail("report-only attempted ownership mutation"),
        )
        report_patch.setattr(
            Path,
            "chmod",
            lambda *_args, **_kwargs: pytest.fail("report-only attempted mode mutation"),
        )
        assert installer.repair_runner_access(root, revision, "6" * 64, manifest_sha, False) == 0
    assert tree_bytes(root) == before
    assert tree_metadata(root) == metadata_before
    report = capsys.readouterr().out
    assert report.splitlines() == [
        f"runnerRevision={revision}",
        f"runnerManifestSha256={manifest_sha}",
        "runnerAccess=repair-required mutation=none authorization=required",
    ]
    assert not any(word in report for word in ("credential", "result", "journal", "payload"))

    assert installer.repair_runner_access(root, revision, "6" * 64, manifest_sha, True) == 0
    assert "metadata-only" in capsys.readouterr().out
    assert tree_bytes(root) == before
    metadata_after = tree_metadata(root)
    changed = {path for path in metadata_before if metadata_before[path] != metadata_after[path]}
    approved = {
        "var/lib/sugarkube",
        "var/lib/sugarkube/dspace-chat-runners",
    }
    approved.update(str(path.relative_to(root)) for path in [runner, *runner.rglob("*")])
    assert changed and changed <= approved
    assert not any("dspace-chat-installations" in path for path in changed)
    assert stat.S_IMODE(runner.stat().st_mode) == 0o750
    assert installer.repair_runner_access(root, revision, "6" * 64, manifest_sha, True) == 0
    assert "already-correct mutation=none" in capsys.readouterr().out


def test_access_repair_preserves_normalized_git_index_through_post_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    value, built_runner = runtime_runner(tmp_path)
    revision = value["runnerRevision"]
    root = tmp_path / "repair-root"
    root.mkdir()
    retained = root / "var/lib/sugarkube/dspace-chat-installations" / ("6" * 64)
    installer.render(retained)
    installer.activate(retained, root, retained.name)
    runner = root / "var/lib/sugarkube/dspace-chat-runners" / revision
    runner.parent.mkdir(parents=True)
    __import__("shutil").copytree(built_runner, runner, symlinks=True)

    class RepairRuntime:
        RUNNER_LOCAL = runtime.RUNNER_LOCAL
        SYSTEM_CHROMIUM = runtime.SYSTEM_CHROMIUM

        @staticmethod
        def load_config(path: Path) -> dict:
            loaded = runtime.load_config(path)
            loaded.update(
                runnerRevision=revision,
                browserContract={"name": runtime.RUNNER_LOCAL},
            )
            return loaded

        validate_runner = staticmethod(runtime.validate_runner)

        @staticmethod
        def validate_browser_contract(_config: dict, selected: Path, _root: Path) -> dict:
            return json.loads((selected / "sugarkube-runner-manifest.json").read_text())[
                "browserProvenance"
            ]

    real_run = subprocess.run

    def fake_node(argv, *args, **kwargs):
        if argv[0] == "/usr/bin/node":
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=str(runner / "playwright-browser/browser-executable").encode(),
            )
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(installer, "runtime_module", lambda: RepairRuntime())
    monkeypatch.setattr(runtime.subprocess, "run", fake_node)
    repair_config = RepairRuntime.load_config(retained / "etc/sugarkube/dspace-chat-synthetic.json")
    installer.normalize_runner_access(repair_config, runner, root)
    index = runner / ".git/index"
    index.chmod(0o600)
    refresh_tracked_stat(runner)
    access_plan = installer.runner_access_plan(repair_config, runner, root)
    mismatches = []
    for path, uid, gid, mode, _follow_symlinks in access_plan:
        info = path.lstat()
        if (
            (info.st_uid, info.st_gid) != (uid, gid)
            or mode is not None
            and stat.S_IMODE(info.st_mode) != mode
        ):
            mismatches.append((path, uid, gid, mode, info))
    assert len(mismatches) == 1
    path, uid, gid, mode, info = mismatches[0]
    assert path == index
    assert mode == 0o640
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert (info.st_uid, info.st_gid) == (uid, gid)
    assert info.st_nlink == 1
    manifest = runner / "sugarkube-runner-manifest.json"
    manifest_sha = installer.sha(manifest)
    bytes_before = tree_bytes(root)
    symlinks_before = {
        str(path.relative_to(root)): os.readlink(path)
        for path in root.rglob("*")
        if path.is_symlink()
    }
    retained_manifest_before = (retained / "manifest.json").read_bytes()
    runner_manifest_before = manifest.read_bytes()
    current_before = os.readlink(retained.parent / "current")

    previous_umask = os.umask(0o077)
    try:
        result = installer.repair_runner_access(root, revision, retained.name, manifest_sha, True)
    finally:
        os.umask(previous_umask)

    assert result == 0
    assert "runnerAccess=repaired mutation=metadata-only" in capsys.readouterr().out
    assert stat.S_IMODE((runner / ".git/index").stat().st_mode) == 0o640
    assert tree_bytes(root) == bytes_before
    assert retained_manifest_before == (retained / "manifest.json").read_bytes()
    assert runner_manifest_before == manifest.read_bytes()
    assert current_before == os.readlink(retained.parent / "current")
    assert symlinks_before == {
        str(path.relative_to(root)): os.readlink(path)
        for path in root.rglob("*")
        if path.is_symlink()
    }
    metadata_before_report = tree_metadata(root)
    assert installer.repair_runner_access(root, revision, retained.name, manifest_sha, False) == 0
    assert "runnerAccess=already-correct mutation=none" in capsys.readouterr().out
    assert tree_metadata(root) == metadata_before_report
    assert tree_bytes(root) == bytes_before


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize(
    "asset",
    [
        "etc/sugarkube/dspace-chat-synthetic.json",
        "usr/local/libexec/sugarkube-dspace-chat-synthetic",
    ],
)
def test_access_repair_rejects_mismatched_current_asset_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    apply: bool,
    asset: str,
) -> None:
    root, _runner, revision, manifest_sha = access_repair_fixture(tmp_path, monkeypatch)
    live = root / asset
    live.write_bytes(live.read_bytes() + b"tampered\n")
    before_bytes = tree_bytes(root)
    before_metadata = tree_metadata(root)
    current = root / "var/lib/sugarkube/dspace-chat-installations/current"
    current_target = os.readlink(current)

    with pytest.raises(ValueError, match="live asset|live configuration"):
        installer.repair_runner_access(root, revision, "6" * 64, manifest_sha, apply)

    assert tree_bytes(root) == before_bytes
    assert tree_metadata(root) == before_metadata
    assert os.readlink(current) == current_target


@pytest.mark.parametrize(
    "fault", ["revision", "manifest", "current", "runner-symlink", "git", "dependency"]
)
def test_access_repair_rejects_ambiguous_or_invalid_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    root, runner, revision, manifest_sha = access_repair_fixture(tmp_path, monkeypatch)
    selected = revision
    if fault == "revision":
        selected = "1" * 40
    elif fault == "manifest":
        manifest_sha = "0" * 64
    elif fault == "current":
        (root / "var/lib/sugarkube/dspace-chat-installations/current").unlink()
    elif fault == "runner-symlink":
        external = tmp_path / "external"
        runner.rename(external)
        runner.symlink_to(external, target_is_directory=True)
    elif fault == "git":
        __import__("shutil").rmtree(runner / ".git")
    else:
        (runner / "dependency.ok").unlink()
    before = tree_bytes(root)
    with pytest.raises((ValueError, OSError)):
        installer.repair_runner_access(root, selected, "6" * 64, manifest_sha, True)
    assert tree_bytes(root) == before


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
