from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts import pi_cluster_bootstrap as bootstrap
from sugarkube_toolkit.pi_cluster import bootstrap as core


class _StubRunner:
    def __init__(self, *, dry_run: bool = False, responses: list[object] | None = None) -> None:
        self.dry_run = dry_run
        self.run_calls: list[list[str]] = []
        self.capture_calls: list[list[str]] = []
        self.json_calls: list[list[str]] = []
        self._responses = list(responses or [])

    def run(self, command: list[str]) -> None:
        self.run_calls.append(command)

    def capture(self, command: list[str]) -> str:
        self.capture_calls.append(command)
        return ""

    def json(self, command: list[str]):  # type: ignore[override]
        self.json_calls.append(command)
        if self._responses:
            return self._responses.pop(0)
        return None


def test_load_wifi_config_requires_ssid() -> None:
    with pytest.raises(core.BootstrapError):
        core._load_wifi_config({"psk": "secret"})


def test_normalize_download_args_injects_mode_only_when_needed() -> None:
    workflow = core.WorkflowConfig(trigger=True)

    appended = core._normalize_download_args([], workflow)
    assert appended[-2:] == ["--mode", "workflow"]

    original = ["--mode", "manual", "--speed", "fast"]
    normalized = core._normalize_download_args(original, workflow)
    assert normalized.count("--mode") == 1
    assert normalized[-1] == "fast"


def test_command_runner_json_bails_when_dry_run(tmp_path: Path) -> None:
    runner = core.CommandRunner(repo_root=tmp_path, dry_run=True)

    result = runner.json(["echo", "{}"])

    assert result is None


def test_execute_returns_stdout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class Result:
        returncode = 0
        stdout = '{"ok": true}'

    monkeypatch.setattr(core.subprocess, "run", lambda *args, **kwargs: Result())

    output = core._execute(["echo", "{}"], repo_root=tmp_path, dry_run=False, capture_output=True)

    assert output == '{"ok": true}'


def test_execute_raises_on_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class Result:
        returncode = 7
        stdout = ""

    monkeypatch.setattr(core.subprocess, "run", lambda *args, **kwargs: Result())

    with pytest.raises(core.BootstrapError) as exc:
        core._execute(["false"], repo_root=tmp_path, dry_run=False)

    assert "exit code 7" in str(exc.value)


def test_ensure_scripts_exist_detects_missing_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "missing.sh"
    monkeypatch.setattr(core, "INSTALL_SCRIPT", missing)
    monkeypatch.setattr(core, "FLASH_REPORT_SCRIPT", missing)
    monkeypatch.setattr(core, "JOIN_REHEARSAL_SCRIPT", missing)

    with pytest.raises(core.BootstrapError) as exc:
        core._ensure_scripts_exist()

    assert str(missing) in str(exc.value)


def test_ensure_gh_available_requires_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core, "which", lambda _name: None)

    with pytest.raises(core.BootstrapError):
        core._ensure_gh_available()


def test_dispatch_workflow_dry_run_invokes_list(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _StubRunner(dry_run=True)
    workflow = core.WorkflowConfig(trigger=True, ref="dev")

    result = core._dispatch_workflow(workflow, runner)

    assert runner.run_calls[0][:3] == ["gh", "workflow", "run"]
    assert runner.capture_calls == [core._build_workflow_list_command("dev")]
    assert result is None


def test_dispatch_workflow_requires_run_id(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _StubRunner(responses=[[]])
    workflow = core.WorkflowConfig(trigger=True)
    monkeypatch.setattr(core, "_ensure_gh_available", lambda: None)
    monkeypatch.setattr(core.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(core, "_wait_for_workflow_completion", lambda *_args, **_kwargs: None)

    with pytest.raises(core.BootstrapError):
        core._dispatch_workflow(workflow, runner)


def test_dispatch_workflow_handles_object_response(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _StubRunner(responses=[{"databaseId": 321}])
    workflow = core.WorkflowConfig(trigger=True)
    captured: dict[str, str] = {}

    monkeypatch.setattr(core, "_ensure_gh_available", lambda: None)
    monkeypatch.setattr(core.time, "sleep", lambda _seconds: None)

    def fake_wait(run_id: str, workflow_cfg: core.WorkflowConfig, runner_obj: _StubRunner) -> None:
        captured["run_id"] = run_id
        assert runner_obj is runner
        assert workflow_cfg is workflow

    monkeypatch.setattr(core, "_wait_for_workflow_completion", fake_wait)

    result = core._dispatch_workflow(workflow, runner)

    assert captured["run_id"] == "321"
    assert result == "321"


def test_wait_for_workflow_completion_skips_for_dry_run() -> None:
    workflow = core.WorkflowConfig(trigger=True)
    runner = _StubRunner(dry_run=True)

    core._wait_for_workflow_completion("123", workflow, runner)

    assert runner.json_calls == []


def test_wait_for_workflow_completion_handles_success(monkeypatch: pytest.MonkeyPatch) -> None:
    workflow = core.WorkflowConfig(trigger=True, wait=True)
    runner = _StubRunner(responses=[{"status": "completed", "conclusion": "success"}])

    monkeypatch.setattr(core.time, "sleep", lambda _seconds: None)

    core._wait_for_workflow_completion("123", workflow, runner)


def test_wait_for_workflow_completion_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    workflow = core.WorkflowConfig(trigger=True, wait=True)
    runner = _StubRunner(responses=[{"status": "completed", "conclusion": "failure"}])

    monkeypatch.setattr(core.time, "sleep", lambda _seconds: None)

    with pytest.raises(core.BootstrapError):
        core._wait_for_workflow_completion("123", workflow, runner)


def test_wait_for_workflow_completion_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    workflow = core.WorkflowConfig(trigger=True, wait=True, wait_timeout=5, poll_interval=1)
    runner = _StubRunner()

    def always_in_progress(command: list[str]) -> dict[str, str]:
        runner.json_calls.append(command)
        return {"status": "in_progress"}

    monkeypatch.setattr(runner, "json", always_in_progress)

    monotonic_values = iter([0, 3, 6, 9])
    monkeypatch.setattr(core.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(core.time, "sleep", lambda _seconds: None)

    with pytest.raises(core.BootstrapError):
        core._wait_for_workflow_completion("123", workflow, runner)


def test_wait_for_workflow_completion_returns_when_data_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = core.WorkflowConfig(trigger=True, wait=True)
    runner = _StubRunner(responses=[None])

    monkeypatch.setattr(core.time, "sleep", lambda _seconds: None)

    core._wait_for_workflow_completion("123", workflow, runner)


def test_run_bootstrap_invokes_workflow_and_join(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    image_path = image_dir / "sugarkube.img"
    image_path.write_text("image")
    base_cloud = tmp_path / "base.yaml"
    base_cloud.write_text("#cloud-config\n")
    report_root = tmp_path / "reports"
    report_root.mkdir()

    defaults = core.NodeDefaults(
        use_sudo=False,
        base_cloud_init=base_cloud,
        report_root=report_root,
    )
    node = core.NodeConfig(
        device="/dev/sdz",
        name="alpha",
        report_dir=report_root / "alpha",
        use_sudo=False,
    )
    workflow = core.WorkflowConfig(trigger=True)
    join = core.JoinConfig(server="controller")
    config = core.ClusterConfig(
        image_dir=image_dir,
        image_name=image_path.name,
        download_args=["--mode", "workflow"],
        nodes=[node],
        join=join,
        defaults=defaults,
        workflow=workflow,
    )

    dispatched: dict[str, core.WorkflowConfig] = {}

    monkeypatch.setattr(core, "_ensure_scripts_exist", lambda: None)

    def fake_dispatch(workflow_cfg: core.WorkflowConfig, runner_obj: _StubRunner) -> str:
        dispatched["config"] = workflow_cfg
        runner_obj.run(["workflow-dispatched"])
        return "999"

    monkeypatch.setattr(core, "_dispatch_workflow", fake_dispatch)

    created: list[_StubRunner] = []

    def make_runner(*, repo_root: Path, dry_run: bool) -> _StubRunner:
        runner_obj = _StubRunner(dry_run=dry_run)
        created.append(runner_obj)
        return runner_obj

    monkeypatch.setattr(core, "CommandRunner", make_runner)

    core.run_bootstrap(config, dry_run=False, skip_download=False, skip_join=False)

    assert dispatched["config"] is workflow
    runner = created[0]
    assert any("workflow-dispatched" in cmd for cmd in runner.run_calls)
    assert any(
        str(core.INSTALL_SCRIPT) in cmd and "--workflow-run" in cmd and "999" in cmd
        for cmd in runner.run_calls
        if isinstance(cmd, list)
    )
    assert any(
        str(image_path) in cmd
        for cmd in runner.run_calls
        if isinstance(cmd, list)
    )


def test_run_bootstrap_respects_skip_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    image_path = image_dir / "sugarkube.img"
    image_path.write_text("image")
    base_cloud = tmp_path / "base.yaml"
    base_cloud.write_text("#cloud-config\n")
    report_root = tmp_path / "reports"
    report_root.mkdir()

    defaults = core.NodeDefaults(
        base_cloud_init=base_cloud,
        report_root=report_root,
    )
    node = core.NodeConfig(device="/dev/sdz", name="beta", report_dir=report_root / "beta")
    workflow = core.WorkflowConfig(trigger=True)
    config = core.ClusterConfig(
        image_dir=image_dir,
        image_name=image_path.name,
        download_args=[],
        nodes=[node],
        join=None,
        defaults=defaults,
        workflow=workflow,
    )

    monkeypatch.setattr(core, "_ensure_scripts_exist", lambda: None)
    dispatch_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_dispatch(*args: object, **kwargs: object) -> None:
        dispatch_calls.append((args, kwargs))

    monkeypatch.setattr(core, "_dispatch_workflow", fake_dispatch)

    created: list[_StubRunner] = []

    def make_runner(*, repo_root: Path, dry_run: bool) -> _StubRunner:
        runner_obj = _StubRunner(dry_run=dry_run)
        created.append(runner_obj)
        return runner_obj

    monkeypatch.setattr(core, "CommandRunner", make_runner)

    core.run_bootstrap(config, dry_run=False, skip_download=True, skip_join=True)

    captured = capsys.readouterr()
    assert "Skipping workflow trigger" in captured.out
    runner = created[0]
    assert dispatch_calls == []
    assert all(str(core.INSTALL_SCRIPT) not in cmd for cmd in runner.run_calls)


def test_parse_args_round_trips_flags() -> None:
    args = bootstrap.parse_args(
        ["--config", "cluster.toml", "--dry-run", "--skip-download", "--skip-join"]
    )

    assert args.config == "cluster.toml"
    assert args.dry_run is True
    assert args.skip_download is True
    assert args.skip_join is True


def test_main_invokes_bootstrap_pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "cluster.toml"
    config_path.write_text("# config")
    sentinel_config = object()
    received: dict[str, object] = {}

    def fake_load(path: Path) -> object:
        received["path"] = path
        return sentinel_config

    def fake_run(
        config: object,
        *,
        dry_run: bool,
        skip_download: bool,
        skip_join: bool,
    ) -> None:
        received["config"] = config
        received["dry_run"] = dry_run
        received["skip_download"] = skip_download
        received["skip_join"] = skip_join

    monkeypatch.setattr(bootstrap, "load_cluster_config", fake_load)
    monkeypatch.setattr(bootstrap, "run_bootstrap", fake_run)

    exit_code = bootstrap.main(["--config", str(config_path), "--dry-run", "--skip-join"])

    assert exit_code == 0
    assert received["path"] == config_path.resolve()
    assert received["config"] is sentinel_config
    assert received["dry_run"] is True
    assert received["skip_download"] is False
    assert received["skip_join"] is True


def test_main_surfaces_bootstrap_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(_path: Path) -> object:
        raise bootstrap.BootstrapError("broken")

    monkeypatch.setattr(bootstrap, "load_cluster_config", boom)

    exit_code = bootstrap.main(["--config", str(tmp_path / "missing.toml")])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "broken" in captured.err


def test_render_cloud_init_injects_hostname_and_wifi() -> None:
    base = "#cloud-config\npackage_update: true\n"
    defaults = bootstrap.NodeDefaults(
        ssh_authorized_keys=["ssh-ed25519 AAAA... test"],
        wifi=bootstrap.WifiConfig(ssid="TestNet", psk="secret"),
    )
    node = bootstrap.NodeConfig(
        device="/dev/sda",
        hostname="sugar-control",
        report_dir=Path("/tmp/reports"),
    )

    rendered = bootstrap.render_cloud_init(base, node, defaults)

    assert "hostname: sugar-control" in rendered
    assert "ssh_authorized_keys:" in rendered
    assert "TestNet" in rendered
    assert rendered.startswith("#cloud-config\n")


def test_build_flash_command_includes_sudo_and_overrides(tmp_path: Path) -> None:
    node = bootstrap.NodeConfig(
        device="/dev/sdb",
        name="worker",
        report_dir=tmp_path / "reports",
    )
    cloud_init = tmp_path / "worker-user-data.yaml"
    command = bootstrap.build_flash_command(
        node,
        Path("/images/sugarkube.img"),
        cloud_init=cloud_init,
    )

    assert command[0] == "sudo"
    assert command[1] == sys.executable
    assert "--cloud-init" in command
    assert str(cloud_init) in command


def test_build_join_command_round_trips_arguments(tmp_path: Path) -> None:
    identity = tmp_path / "id_ed25519"
    identity.write_text("dummy")
    join = bootstrap.JoinConfig(
        server="control.local",
        agents=["worker-a.local", "worker-b.local"],
        agent_user="pi",
        identity=identity,
        apply_wait_timeout=600,
        api_port=6443,
        extra_args=["--connect-timeout", "15"],
    )

    command = bootstrap.build_join_command(join)

    assert "--agents" in command
    assert "--apply-wait-timeout" in command
    assert str(identity) in command
    assert command.count("--connect-timeout") == 1


def test_load_cluster_config_resolves_relative_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "cluster.toml"
    config_path.write_text(
        """
[image]
dir = "./images"
name = "custom.img"

[defaults]
use_sudo = false
report_root = "./reports"
ssh_authorized_keys = ["ssh-ed25519 AAAA... test"]

[[nodes]]
device = "/dev/sda"
hostname = "control"
report_dir = "./reports/control"

[[nodes]]
device = "/dev/sdb"
hostname = "worker"

[cluster.join]
server = "control.local"
agents = ["worker.local"]
identity = "./id_ed25519"
apply_wait_timeout = 420
"""
    )
    (tmp_path / "images").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "control").mkdir()
    (tmp_path / "id_ed25519").write_text("dummy")

    config = bootstrap.load_cluster_config(config_path)

    assert config.image_dir == (tmp_path / "images").resolve()
    assert config.image_name == "custom.img"
    assert config.nodes[0].report_dir == (tmp_path / "reports" / "control").resolve()
    assert config.nodes[1].report_dir == (tmp_path / "reports" / "worker").resolve()
    assert config.join is not None
    assert config.join.apply_wait_timeout == 420
    assert config.join.identity == (tmp_path / "id_ed25519").resolve()


def test_load_cluster_config_enables_workflow_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "cluster.toml"
    config_path.write_text(
        """
[image]
download_args = []
[image.workflow]
trigger = true
clone_token_place = true

[[nodes]]
device = "/dev/sdz"
hostname = "controller"
"""
    )

    config = bootstrap.load_cluster_config(config_path)

    assert "--mode" in config.download_args
    assert "workflow" in config.download_args
    assert config.workflow is not None
    assert config.workflow.clone_token_place is True


def test_build_install_command_appends_workflow_run_id(tmp_path: Path) -> None:
    config = bootstrap.ClusterConfig(
        image_dir=tmp_path,
        image_name="sugarkube.img",
        download_args=["--mode", "workflow"],
        nodes=[],
        join=None,
        defaults=bootstrap.NodeDefaults(),
    )

    command = bootstrap.build_install_command(config, workflow_run_id="12345")

    assert command.count("--workflow-run") == 1
    assert command[-2:] == ["--workflow-run", "12345"]
    assert str(tmp_path / "sugarkube.img") in command


def test_build_install_command_respects_existing_workflow_run_id(tmp_path: Path) -> None:
    config = bootstrap.ClusterConfig(
        image_dir=tmp_path,
        image_name="custom.img",
        download_args=["--workflow-run", "abc", "--mode", "workflow"],
        nodes=[],
        join=None,
        defaults=bootstrap.NodeDefaults(),
    )

    command = bootstrap.build_install_command(config, workflow_run_id="xyz")

    assert command.count("--workflow-run") == 1
    assert command[-4:-2] == ["--workflow-run", "abc"]


def test_build_workflow_dispatch_command_sets_inputs() -> None:
    workflow = bootstrap.WorkflowConfig(
        trigger=True,
        ref="main",
        clone_sugarkube=True,
        clone_token_place=False,
        clone_dspace=True,
    )

    command = bootstrap.build_workflow_dispatch_command(workflow)

    assert command[:4] == ["gh", "workflow", "run", "pi-image.yml"]
    assert "--field" in command
    assert any("clone_sugarkube=true" in part for part in command)
    assert any("clone_token_place=false" in part for part in command)
