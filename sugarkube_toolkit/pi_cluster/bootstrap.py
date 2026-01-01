from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from shlex import quote as shlex_quote
from shutil import which
from typing import Any, Sequence

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError as exc:  # pragma: no cover - Python < 3.11 guard
    raise SystemExit("python 3.11+ is required to load TOML cluster configs") from exc

MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
INSTALL_SCRIPT = SCRIPTS_DIR / "install_sugarkube_image.sh"
FLASH_REPORT_SCRIPT = SCRIPTS_DIR / "flash_pi_media_report.py"
JOIN_REHEARSAL_SCRIPT = SCRIPTS_DIR / "pi_multi_node_join_rehearsal.py"
DEFAULT_BASE_CLOUD_INIT = SCRIPTS_DIR / "cloud-init" / "user-data.yaml"
DEFAULT_IMAGE_DIR = Path.home() / "sugarkube" / "images"
DEFAULT_IMAGE_NAME = "sugarkube.img"
DEFAULT_REPORT_ROOT = Path.home() / "sugarkube" / "reports" / "cluster"
WORKFLOW_FILE = "pi-image.yml"


class BootstrapError(RuntimeError):
    """Raised when the bootstrap workflow cannot complete."""


@dataclass(slots=True)
class WifiConfig:
    """Wi-Fi credentials injected into per-node cloud-init overrides."""

    ssid: str
    psk: str | None = None
    country: str | None = None
    hidden: bool = False


@dataclass(slots=True)
class NodeDefaults:
    """Reusable defaults applied across every node unless overridden."""

    use_sudo: bool = True
    no_eject: bool = False
    keep_mounted: bool = False
    ssh_authorized_keys: list[str] = field(default_factory=list)
    wifi: WifiConfig | None = None
    base_cloud_init: Path = DEFAULT_BASE_CLOUD_INIT
    report_root: Path = DEFAULT_REPORT_ROOT
    extra_flash_args: list[str] = field(default_factory=list)


@dataclass(slots=True)
class NodeConfig:
    """Information required to flash and tag an individual Raspberry Pi."""

    device: str
    name: str | None = None
    hostname: str | None = None
    role: str | None = None
    cloud_init_path: Path | None = None
    use_sudo: bool = True
    no_eject: bool = False
    keep_mounted: bool = False
    ssh_authorized_keys: list[str] = field(default_factory=list)
    wifi: WifiConfig | None = None
    extra_flash_args: list[str] = field(default_factory=list)
    report_dir: Path | None = None

    def identifier(self) -> str:
        if self.name:
            return self.name
        if self.hostname:
            return self.hostname
        return self.device.replace("/", "_")


@dataclass(slots=True)
class JoinConfig:
    """Parameters forwarded to the multi-node join rehearsal."""

    server: str
    agents: list[str] = field(default_factory=list)
    server_user: str | None = None
    agent_user: str | None = None
    identity: Path | None = None
    apply: bool = True
    apply_wait: bool = True
    apply_wait_timeout: int | None = None
    apply_wait_interval: int | None = None
    api_port: int | None = None
    api_timeout: int | None = None
    connect_timeout: int | None = None
    secret_path: str | None = None
    extra_args: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WorkflowConfig:
    """Options for dispatching and monitoring the pi-image workflow."""

    trigger: bool = False
    ref: str = "main"
    clone_sugarkube: bool = False
    clone_token_place: bool = False
    clone_dspace: bool = False
    wait: bool = True
    wait_timeout: int | None = 7200
    poll_interval: int = 30

    def requires_download_mode(self) -> bool:
        return self.trigger

    def inputs(self) -> dict[str, str]:
        return {
            "clone_sugarkube": _bool_to_str(self.clone_sugarkube),
            "clone_token_place": _bool_to_str(self.clone_token_place),
            "clone_dspace": _bool_to_str(self.clone_dspace),
        }


@dataclass(slots=True)
class ClusterConfig:
    """Fully parsed cluster configuration."""

    image_dir: Path
    image_name: str
    download_args: list[str]
    nodes: list[NodeConfig]
    join: JoinConfig | None
    defaults: NodeDefaults
    workflow: WorkflowConfig | None = None

    @property
    def image_path(self) -> Path:
        return self.image_dir / self.image_name


class CommandRunner:
    """Execute shell commands with optional dry-run support."""

    def __init__(self, *, repo_root: Path, dry_run: bool):
        self.repo_root = repo_root
        self.dry_run = dry_run

    def run(self, command: Sequence[str]) -> None:
        _execute(command, repo_root=self.repo_root, dry_run=self.dry_run)

    def capture(self, command: Sequence[str]) -> str:
        return _execute(
            command,
            repo_root=self.repo_root,
            dry_run=self.dry_run,
            capture_output=True,
        )

    def json(self, command: Sequence[str]) -> Any:
        output = self.capture(command)
        if self.dry_run:
            return None
        if not output:
            return None
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise BootstrapError(
                "Failed to parse JSON output from command: " f"{_format_command(command)}"
            ) from exc


def _execute(
    command: Sequence[str],
    *,
    repo_root: Path,
    dry_run: bool,
    capture_output: bool = False,
) -> str:
    printable = _format_command(command)
    if dry_run:
        _log(f"DRY-RUN: {printable}")
        return ""
    _log(printable)
    result = subprocess.run(
        command,
        cwd=str(repo_root),
        check=False,
        text=True,
        capture_output=capture_output,
    )
    if result.returncode != 0:
        raise BootstrapError(f"Command failed with exit code {result.returncode}: {printable}")
    if capture_output:
        return (result.stdout or "").strip()
    return ""


def _log(message: str) -> None:
    print(f"==> {message}")


def _format_command(command: Sequence[str]) -> str:
    return " ".join(shlex_quote(part) for part in command)


def _bool_to_str(value: bool) -> str:
    return "true" if value else "false"


def _expand_path(value: str, *, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base / path).resolve()
    return path


def _load_wifi_config(raw: dict[str, object] | None) -> WifiConfig | None:
    if not raw:
        return None
    ssid = str(raw.get("ssid", "")).strip()
    if not ssid:
        raise BootstrapError("wifi.ssid must be provided when wifi configuration is supplied")
    psk_value = raw.get("psk")
    psk = str(psk_value).strip() if psk_value is not None else None
    country_value = raw.get("country")
    country = str(country_value).strip() if country_value is not None else None
    hidden = bool(raw.get("hidden", False))
    return WifiConfig(ssid=ssid, psk=psk or None, country=country or None, hidden=hidden)


def _normalize_download_args(
    download_args: list[str], workflow: WorkflowConfig | None
) -> list[str]:
    if not workflow or not workflow.requires_download_mode():
        return download_args
    args = list(download_args)
    has_mode_flag = any(part == "--mode" for part in args)
    if not has_mode_flag:
        args.extend(["--mode", "workflow"])
    return args


def load_cluster_config(path: Path) -> ClusterConfig:
    if not path.exists():
        raise BootstrapError(f"Cluster configuration not found: {path}")

    data = tomllib.loads(path.read_text())
    base_dir = path.parent

    image_section = data.get("image", {})
    image_dir_value = image_section.get("dir")
    if image_dir_value:
        image_dir = _expand_path(str(image_dir_value), base=base_dir)
    else:
        image_dir = DEFAULT_IMAGE_DIR
    image_name = str(image_section.get("name", DEFAULT_IMAGE_NAME))

    workflow_section = image_section.get("workflow") if isinstance(image_section, dict) else None
    workflow: WorkflowConfig | None = None
    if isinstance(workflow_section, dict):
        workflow = WorkflowConfig(
            trigger=bool(workflow_section.get("trigger", False)),
            ref=str(workflow_section.get("ref", "main")),
            clone_sugarkube=bool(workflow_section.get("clone_sugarkube", False)),
            clone_token_place=bool(workflow_section.get("clone_token_place", False)),
            clone_dspace=bool(workflow_section.get("clone_dspace", False)),
            wait=bool(workflow_section.get("wait", True)),
            wait_timeout=(
                int(workflow_section["wait_timeout"])
                if workflow_section.get("wait_timeout") is not None
                else 7200
            ),
            poll_interval=(
                int(workflow_section["poll_interval"])
                if workflow_section.get("poll_interval") is not None
                else 30
            ),
        )

    download_args = [str(part) for part in image_section.get("download_args", [])]
    download_args = _normalize_download_args(download_args, workflow)

    defaults_section = data.get("defaults", {})
    defaults_wifi = _load_wifi_config(
        defaults_section.get("wifi") if isinstance(defaults_section.get("wifi"), dict) else None
    )

    base_cloud_init_value = defaults_section.get("base_cloud_init")
    if base_cloud_init_value:
        base_cloud_init = _expand_path(str(base_cloud_init_value), base=base_dir)
    else:
        base_cloud_init = DEFAULT_BASE_CLOUD_INIT

    report_root_value = defaults_section.get("report_root")
    if report_root_value:
        report_root = _expand_path(str(report_root_value), base=base_dir)
    else:
        report_root = DEFAULT_REPORT_ROOT

    defaults = NodeDefaults(
        use_sudo=bool(defaults_section.get("use_sudo", True)),
        no_eject=bool(defaults_section.get("no_eject", False)),
        keep_mounted=bool(defaults_section.get("keep_mounted", False)),
        ssh_authorized_keys=[str(key) for key in defaults_section.get("ssh_authorized_keys", [])],
        wifi=defaults_wifi,
        base_cloud_init=base_cloud_init,
        report_root=report_root,
        extra_flash_args=[str(part) for part in defaults_section.get("extra_flash_args", [])],
    )

    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise BootstrapError("At least one node must be defined under [[nodes]].")

    nodes: list[NodeConfig] = []
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            raise BootstrapError("Node entries must be tables (TOML dictionaries).")
        device_value = raw_node.get("device")
        if not device_value:
            raise BootstrapError("Each node requires a device path (e.g. /dev/sdX).")
        cloud_init_value = raw_node.get("cloud_init")
        cloud_init_path = (
            _expand_path(str(cloud_init_value), base=base_dir) if cloud_init_value else None
        )
        wifi_cfg = defaults.wifi
        if raw_node.get("wifi") and isinstance(raw_node.get("wifi"), dict):
            wifi_cfg = _load_wifi_config(raw_node.get("wifi"))
        report_dir_value = raw_node.get("report_dir")
        if report_dir_value:
            report_dir = _expand_path(str(report_dir_value), base=base_dir)
        else:
            fallback_name = raw_node.get("name") or raw_node.get("hostname") or "node"
            report_dir = defaults.report_root / str(fallback_name)
        node = NodeConfig(
            device=str(device_value),
            name=str(raw_node.get("name")) if raw_node.get("name") else None,
            hostname=str(raw_node.get("hostname")) if raw_node.get("hostname") else None,
            role=str(raw_node.get("role")) if raw_node.get("role") else None,
            cloud_init_path=cloud_init_path,
            use_sudo=bool(raw_node.get("use_sudo", defaults.use_sudo)),
            no_eject=bool(raw_node.get("no_eject", defaults.no_eject)),
            keep_mounted=bool(raw_node.get("keep_mounted", defaults.keep_mounted)),
            ssh_authorized_keys=[
                str(key)
                for key in raw_node.get("ssh_authorized_keys", defaults.ssh_authorized_keys)
            ],
            wifi=wifi_cfg,
            extra_flash_args=[
                str(part) for part in raw_node.get("extra_flash_args", defaults.extra_flash_args)
            ],
            report_dir=report_dir,
        )
        nodes.append(node)

    cluster_section = data.get("cluster")
    join_section = cluster_section.get("join") if isinstance(cluster_section, dict) else None
    join: JoinConfig | None = None
    if isinstance(join_section, dict):
        server = join_section.get("server")
        if server:
            join = JoinConfig(
                server=str(server),
                agents=[str(agent) for agent in join_section.get("agents", [])],
                server_user=(
                    str(join_section.get("server_user"))
                    if join_section.get("server_user")
                    else None
                ),
                agent_user=(
                    str(join_section.get("agent_user")) if join_section.get("agent_user") else None
                ),
                identity=(
                    _expand_path(str(join_section.get("identity")), base=base_dir)
                    if join_section.get("identity")
                    else None
                ),
                apply=bool(join_section.get("apply", True)),
                apply_wait=bool(join_section.get("apply_wait", True)),
                apply_wait_timeout=(
                    int(join_section.get("apply_wait_timeout"))
                    if join_section.get("apply_wait_timeout") is not None
                    else None
                ),
                apply_wait_interval=(
                    int(join_section.get("apply_wait_interval"))
                    if join_section.get("apply_wait_interval") is not None
                    else None
                ),
                api_port=(
                    int(join_section.get("api_port"))
                    if join_section.get("api_port") is not None
                    else None
                ),
                api_timeout=(
                    int(join_section.get("api_timeout"))
                    if join_section.get("api_timeout") is not None
                    else None
                ),
                connect_timeout=(
                    int(join_section.get("connect_timeout"))
                    if join_section.get("connect_timeout") is not None
                    else None
                ),
                secret_path=(
                    str(join_section.get("secret_path"))
                    if join_section.get("secret_path")
                    else None
                ),
                extra_args=[str(part) for part in join_section.get("extra_args", [])],
            )

    return ClusterConfig(
        image_dir=image_dir,
        image_name=image_name,
        download_args=download_args,
        nodes=nodes,
        join=join,
        defaults=defaults,
        workflow=workflow,
    )


def render_cloud_init(base: str, node: NodeConfig, defaults: NodeDefaults) -> str:
    if not base.startswith("#cloud-config"):
        raise BootstrapError("Base cloud-init file must start with '#cloud-config'.")
    lines = base.splitlines()
    header, body = lines[0], lines[1:]
    rendered: list[str] = [header]
    if node.hostname:
        rendered.append(f"hostname: {node.hostname}")
        rendered.append("preserve_hostname: false")
        rendered.append("manage_etc_hosts: true")
    if node.role:
        rendered.append(f"# sugarkube role: {node.role}")
    keys = node.ssh_authorized_keys or defaults.ssh_authorized_keys
    if keys:
        rendered.append("ssh_authorized_keys:")
        for key in keys:
            rendered.append(f"  - {key}")
    wifi_cfg = node.wifi or defaults.wifi
    if wifi_cfg:
        rendered.extend(_render_wifi_block(wifi_cfg))
    if rendered[-1] != "":
        rendered.append("")
    rendered.extend(body)
    rendered.append("")
    return "\n".join(rendered)


def _render_wifi_block(config: WifiConfig) -> list[str]:
    lines = ["wpa_supplicant:", "  update_config: true", "  ap_scan: 1", "  networks:"]
    network_lines = [f'    - ssid: "{config.ssid}"']
    if config.hidden:
        network_lines.append("      scan_ssid: 1")
    if config.psk:
        network_lines.append(f'      psk: "{config.psk}"')
    else:
        network_lines.append("      key_mgmt: NONE")
    if config.country:
        lines.append(f"country: {config.country}")
    lines.extend(network_lines)
    return lines


def _append_workflow_run_arg(args: list[str], workflow_run_id: str | None) -> list[str]:
    if not workflow_run_id:
        return args
    if any(part == "--workflow-run" for part in args):
        return args
    return [*args, "--workflow-run", workflow_run_id]


def build_install_command(
    config: ClusterConfig, *, workflow_run_id: str | None = None
) -> list[str]:
    command: list[str] = [
        "bash",
        str(INSTALL_SCRIPT),
        "--dir",
        str(config.image_dir),
        "--image",
        str(config.image_path),
    ]
    command.extend(_append_workflow_run_arg(config.download_args, workflow_run_id))
    return command


def build_flash_command(
    node: NodeConfig, image_path: Path, *, cloud_init: Path | None
) -> list[str]:
    command: list[str] = []
    if node.use_sudo:
        command.append("sudo")
    command.extend(
        [
            sys.executable,
            str(FLASH_REPORT_SCRIPT),
            "--image",
            str(image_path),
            "--device",
            node.device,
            "--assume-yes",
            "--output-dir",
            str(node.report_dir),
        ]
    )
    if node.no_eject:
        command.append("--no-eject")
    if node.keep_mounted:
        command.append("--keep-mounted")
    if cloud_init:
        command.extend(
            [
                "--cloud-init",
                str(cloud_init),
                "--base-cloud-init",
                str(DEFAULT_BASE_CLOUD_INIT),
            ]
        )
    command.extend(node.extra_flash_args)
    return command


def build_join_command(config: JoinConfig) -> list[str]:
    command: list[str] = [sys.executable, str(JOIN_REHEARSAL_SCRIPT), config.server]
    if config.server_user:
        command.extend(["--server-user", config.server_user])
    if config.agent_user:
        command.extend(["--agent-user", config.agent_user])
    if config.identity:
        command.extend(["--identity", str(config.identity)])
    if config.secret_path:
        command.extend(["--secret-path", config.secret_path])
    if config.connect_timeout is not None:
        command.extend(["--connect-timeout", str(config.connect_timeout)])
    if config.api_port is not None:
        command.extend(["--api-port", str(config.api_port)])
    if config.api_timeout is not None:
        command.extend(["--api-timeout", str(config.api_timeout)])
    if config.agents:
        command.append("--agents")
        command.extend(config.agents)
    if config.apply:
        command.append("--apply")
    if config.apply_wait:
        command.append("--apply-wait")
    if config.apply_wait_timeout is not None:
        command.extend(["--apply-wait-timeout", str(config.apply_wait_timeout)])
    if config.apply_wait_interval is not None:
        command.extend(["--apply-wait-interval", str(config.apply_wait_interval)])
    command.extend(config.extra_args)
    return command


def build_workflow_dispatch_command(config: WorkflowConfig) -> list[str]:
    command: list[str] = ["gh", "workflow", "run", WORKFLOW_FILE, "--ref", config.ref]
    for key, value in config.inputs().items():
        command.extend(["--field", f"{key}={value}"])
    return command


def _build_workflow_list_command(ref: str) -> list[str]:
    return [
        "gh",
        "run",
        "list",
        "--workflow",
        WORKFLOW_FILE,
        "--branch",
        ref,
        "--limit",
        "1",
        "--json",
        "databaseId,status,conclusion",
    ]


def _build_workflow_view_command(run_id: str) -> list[str]:
    return ["gh", "run", "view", run_id, "--json", "status,conclusion"]


def _ensure_scripts_exist() -> None:
    missing = [
        script
        for script in (INSTALL_SCRIPT, FLASH_REPORT_SCRIPT, JOIN_REHEARSAL_SCRIPT)
        if not script.exists()
    ]
    if missing:
        joined = ", ".join(str(path) for path in missing)
        raise BootstrapError(f"Required helper scripts are missing: {joined}")


def _ensure_gh_available() -> None:
    if which("gh") is None:
        raise BootstrapError(
            "GitHub CLI (gh) is required to trigger pi-image workflow runs. "
            "Install gh or disable the image.workflow.trigger option."
        )


def _wait_for_workflow_completion(
    run_id: str, workflow: WorkflowConfig, runner: CommandRunner
) -> None:
    if runner.dry_run or not workflow.wait:
        return
    deadline = time.monotonic() + workflow.wait_timeout if workflow.wait_timeout else None
    while True:
        data = runner.json(_build_workflow_view_command(run_id))
        if data is None:
            return
        status = str(data.get("status", "")).lower()
        if status == "completed":
            conclusion = str(data.get("conclusion", "")).lower()
            if conclusion and conclusion != "success":
                raise BootstrapError(
                    f"pi-image workflow run {run_id} completed with status '{conclusion}'."
                )
            return
        if deadline and time.monotonic() >= deadline:
            raise BootstrapError(f"Timed out waiting for pi-image workflow run {run_id} to finish.")
        time.sleep(max(workflow.poll_interval, 1))


def _dispatch_workflow(config: WorkflowConfig, runner: CommandRunner) -> str | None:
    if runner.dry_run:
        runner.run(build_workflow_dispatch_command(config))
        runner.capture(_build_workflow_list_command(config.ref))
        return None

    _ensure_gh_available()
    runner.run(build_workflow_dispatch_command(config))
    time.sleep(2)
    run_list = runner.json(_build_workflow_list_command(config.ref))
    if not run_list:
        raise BootstrapError("Unable to determine pi-image workflow run ID after dispatch.")
    if isinstance(run_list, list):
        run_data = run_list[0] if run_list else None
    else:
        run_data = run_list
    if not run_data or "databaseId" not in run_data:
        raise BootstrapError("pi-image workflow run did not report a databaseId.")
    run_id = str(run_data["databaseId"])
    _log(f"Waiting for pi-image workflow run {run_id} to complete.")
    _wait_for_workflow_completion(run_id, config, runner)
    return run_id


def run_bootstrap(
    config: ClusterConfig,
    *,
    dry_run: bool,
    skip_download: bool,
    skip_join: bool,
) -> None:
    _ensure_scripts_exist()
    runner = CommandRunner(repo_root=REPO_ROOT, dry_run=dry_run)

    workflow_run_id: str | None = None
    if config.workflow and config.workflow.trigger:
        if skip_download:
            _log("Skipping workflow trigger because --skip-download was supplied.")
        else:
            workflow_run_id = _dispatch_workflow(config.workflow, runner)

    if not skip_download:
        install_command = build_install_command(config, workflow_run_id=workflow_run_id)
        runner.run(install_command)
    else:
        _log("Skipping image download (--skip-download supplied).")

    if not config.image_path.exists() and not dry_run:
        raise BootstrapError(
            f"Expanded image not found at {config.image_path}. Run without --skip-download."
        )

    base_cloud_init = config.defaults.base_cloud_init
    if not base_cloud_init.exists():
        raise BootstrapError(f"Base cloud-init template missing: {base_cloud_init}")
    base_content = base_cloud_init.read_text()

    with tempfile.TemporaryDirectory(prefix="sugarkube-cluster-") as tmpdir:
        for node in config.nodes:
            _log(f"Preparing media for {node.identifier()} ({node.device})")
            cloud_init_path = node.cloud_init_path
            if cloud_init_path is None:
                rendered = render_cloud_init(base_content, node, config.defaults)
                node_file = Path(tmpdir) / f"{node.identifier()}-user-data.yaml"
                node_file.write_text(rendered)
                cloud_init_path = node_file
            flash_command = build_flash_command(node, config.image_path, cloud_init=cloud_init_path)
            runner.run(flash_command)

    if config.join and not skip_join:
        join_command = build_join_command(config.join)
        runner.run(join_command)
    elif config.join and skip_join:
        _log("Skipping cluster join (--skip-join supplied).")


__all__ = [
    "BootstrapError",
    "ClusterConfig",
    "CommandRunner",
    "JoinConfig",
    "NodeConfig",
    "NodeDefaults",
    "WifiConfig",
    "WorkflowConfig",
    "build_flash_command",
    "build_install_command",
    "build_join_command",
    "build_workflow_dispatch_command",
    "load_cluster_config",
    "render_cloud_init",
    "run_bootstrap",
]
