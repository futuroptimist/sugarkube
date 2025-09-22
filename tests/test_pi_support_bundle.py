import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "pi_support_bundle.py"
SPEC = importlib.util.spec_from_file_location("pi_support_bundle", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_sanitize_host_replaces_invalid_characters():
    assert MODULE.sanitize_host("pi-a.local") == "pi-a_local"
    assert MODULE.sanitize_host("pi#a+1") == "pi_a_1"


def test_build_remote_commands_includes_since_clause():
    commands = MODULE.build_remote_commands("24 hours ago")
    journal_command = next(cmd for cmd in commands if cmd.path == Path("journal/k3s.log"))
    assert "--since '24 hours ago'" in journal_command.command
    compose_command = next(
        cmd for cmd in commands if cmd.path == Path("compose/projects-compose.log")
    )
    assert "docker compose" in compose_command.command


def test_collector_writes_bundles_and_metadata(tmp_path):
    args = MODULE.parse_args(
        [
            "pi.local",
            "--output-dir",
            str(tmp_path),
            "--skip-first-boot-report",
        ]
    )

    def fake_runner(cmd, capture_output, text, timeout):
        remote = cmd[-1]
        if "docker compose" in remote:
            stdout = "" if text else b""
            stderr = "compose exploded" if text else b"compose exploded"
            return subprocess.CompletedProcess(cmd, 1, stdout=stdout, stderr=stderr)
        if text:
            stdout = f"ok: {remote}"
            stderr = ""
        else:
            stdout = f"ok: {remote}".encode()
            stderr = b""
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr=stderr)

    collector = MODULE.SupportBundleCollector(
        args,
        runner=fake_runner,
        now_fn=lambda: dt.datetime(2025, 1, 1, 0, 0, 0),
    )
    success = collector.collect()
    assert not success  # compose command returned exit 1

    host_dir = next(p for p in tmp_path.iterdir() if p.is_dir())
    metadata_path = host_dir / "metadata.json"
    assert metadata_path.exists()
    metadata = json.loads(metadata_path.read_text())
    assert metadata["host"] == "pi.local"
    compose_entry = next(
        item for item in metadata["commands"] if item["path"] == "compose/projects-compose.log"
    )
    assert compose_entry["note"] == "exit-1"
    log_contents = (host_dir / "compose/projects-compose.log").read_text()
    assert "compose exploded" in log_contents

    archives = list(tmp_path.glob("*.tar.gz"))
    assert archives, "expected tar archive to be created"
