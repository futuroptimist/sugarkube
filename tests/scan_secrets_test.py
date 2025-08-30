import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "scan-secrets.py"


def run_scan(data: str):
    return subprocess.run(
        [str(SCRIPT)],
        input=data,
        text=True,
        capture_output=True,
    )


def test_detects_aws_key():
    key = "AKIA" + "1234567890ABCDEF"
    result = run_scan(key)
    assert result.returncode == 1
    assert "AWS Access Key ID" in result.stdout


def test_passes_clean_input():
    result = run_scan("just some text")
    assert result.returncode == 0
