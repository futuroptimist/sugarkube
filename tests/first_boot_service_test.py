import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "first_boot_service.py"


def _write_verifier(
    tmp_path: Path,
    exit_code: int,
    checks: list[tuple[str, str]],
    stderr: str = "",
) -> Path:
    payload = {"checks": [{"name": name, "status": status} for name, status in checks]}
    script = tmp_path / "verifier.sh"
    log_text = "# verifier log\n"
    escaped_log_text = log_text.replace("\\", "\\\\").replace("\n", "\\n")
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "json=false\n"
        'log_path=""\n'
        "while [[ $# -gt 0 ]]; do\n"
        '  case "$1" in\n'
        "    --json) json=true ;;\n"
        "    --no-log) ;;\n"
        "    --log)\n"
        "      if [[ $# -lt 2 ]]; then\n"
        "        echo '--log requires a value' >&2\n"
        "        exit 64\n"
        "      fi\n"
        '      log_path="$2"\n'
        "      shift ;;\n"
        '    --log=*) log_path="${1#*=}" ;;\n'
        "  esac\n"
        "  shift\n"
        "done\n"
        f"if ${{json}}; then\n"
        f"  printf '%s\\n' '{json.dumps(payload)}'\n"
        "else\n"
        '  if [[ -n "$log_path" ]]; then\n'
        f'    printf \'%s\' "{escaped_log_text}" >> "$log_path"\n'
        "  fi\n"
        "fi\n"
        f'if [[ -n "{stderr}" ]]; then\n'
        f"  printf '%s\\n' '{stderr}' >&2\n"
        "fi\n"
        f"exit {exit_code}\n"
    )
    script.chmod(0o755)
    return script


@pytest.mark.parametrize(
    "exit_code,checks,expected_overall",
    [
        (
            0,
            [
                ("cloud_init", "pass"),
                ("k3s_node_ready", "pass"),
                ("projects_compose_active", "pass"),
                ("token_place_http", "pass"),
                ("dspace_http", "pass"),
            ],
            "pass",
        ),
        (
            2,
            [
                ("cloud_init", "pass"),
                ("k3s_node_ready", "fail"),
                ("projects_compose_active", "fail"),
                ("token_place_http", "fail"),
                ("dspace_http", "fail"),
            ],
            "fail",
        ),
    ],
)
def test_first_boot_service(tmp_path, exit_code, checks, expected_overall):
    report_dir = tmp_path / "report"
    state_dir = tmp_path / "state"
    log_path = tmp_path / "report.txt"
    verifier = _write_verifier(tmp_path, exit_code=exit_code, checks=checks, stderr="warning")

    env = os.environ.copy()
    env.update(
        {
            "FIRST_BOOT_REPORT_DIR": str(report_dir),
            "FIRST_BOOT_STATE_DIR": str(state_dir),
            "FIRST_BOOT_LOG_PATH": str(log_path),
            "FIRST_BOOT_VERIFIER": str(verifier),
            "FIRST_BOOT_ATTEMPTS": "1",
            "FIRST_BOOT_RETRY_DELAY": "0",
        }
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )

    summary_path = report_dir / "summary.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text())
    assert payload["overall"] == expected_overall
    assert payload["summary"]["cloud_init"] == checks[0][1]
    assert payload["summary"]["token_place"] == checks[3][1]

    html_path = report_dir / "summary.html"
    assert html_path.exists()
    html_text = html_path.read_text()
    assert "Sugarkube First Boot Summary" in html_text

    md_path = report_dir / "summary.md"
    assert md_path.exists()
    assert "## Detailed Checks" in md_path.read_text()

    stderr_path = report_dir / "verifier.stderr"
    if exit_code == 0:
        assert result.returncode == 0
        assert (state_dir / "first-boot.ok").exists()
        assert not (state_dir / "first-boot.failed").exists()
        assert stderr_path.exists()
    else:
        assert result.returncode == exit_code
        assert (state_dir / "first-boot.failed").exists()
        assert not (state_dir / "first-boot.ok").exists()
        assert stderr_path.exists()
