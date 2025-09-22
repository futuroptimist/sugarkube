from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import collect_support_bundle


def test_default_specs_cover_required_commands() -> None:
    specs = {
        spec.output_path.as_posix(): spec.remote_command
        for spec in collect_support_bundle.default_specs()
    }
    required = {
        "kubernetes/events.txt": "kubectl get events",
        "helm/releases.txt": "helm list -A",
        "systemd/systemd-analyze-blame.txt": "systemd-analyze blame",
        "compose/docker-compose-logs.txt": "docker compose",
        "journals/journalctl-boot.txt": "journalctl -b",
    }
    for path, snippet in required.items():
        assert path in specs, f"expected {path} in default specs"
        assert snippet in specs[path]


@pytest.mark.parametrize(
    "entry, expected_path",
    [
        ("extra/foo.txt:echo hi:Extra command", Path("extra/foo.txt")),
    ],
)
def test_parse_extra_specs(entry: str, expected_path: Path) -> None:
    spec = collect_support_bundle.parse_extra_specs([entry])[0]
    assert spec.output_path == expected_path
    assert spec.remote_command == "echo hi"
    assert spec.description == "Extra command"


def test_build_bundle_dir_sanitises_host(tmp_path: Path) -> None:
    ts = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    bundle = collect_support_bundle.build_bundle_dir(tmp_path, "pi.local:2222", ts)
    assert bundle.exists()
    assert bundle.name.startswith("pi.local_2222-20240102T030405Z")
