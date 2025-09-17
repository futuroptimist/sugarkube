import json
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]


def run_preset(args, env=None):
    cmd = [sys.executable, str(BASE_DIR / "scripts" / "create_pi_imager_preset.py")]
    cmd.extend(args)
    return subprocess.run(cmd, env=env, capture_output=True, text=True)


def test_generates_preset_json(tmp_path):
    output = tmp_path / "preset.json"
    result = run_preset(
        [
            "--hostname",
            "sugar-pi",
            "--username",
            "sugar",
            "--password",
            "secret",
            "--wifi-ssid",
            "ExampleNet",
            "--wifi-password",
            "wifi-secret",
            "--wifi-country",
            "GB",
            "--ssh-key",
            "ssh-ed25519 AAAATEST user@example",
            "--pretty",
            "--output",
            str(output),
        ]
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    config = data["config"]

    assert config["hostname"] == "sugar-pi"
    assert config["username"] == "sugar"
    assert config["password"].startswith("$6$")
    assert config["ssh"]["enabled"] is True
    assert config["ssh"]["authorized_keys"] == ["ssh-ed25519 AAAATEST user@example"]
    assert config["wifi"]["ssid"] == "ExampleNet"
    assert config["wifi"]["country"] == "GB"
    assert config["wlan"]["ssid"] == "ExampleNet"


def test_wifi_requires_matching_flags(tmp_path):
    result = run_preset(
        [
            "--hostname",
            "example",
            "--username",
            "user",
            "--password",
            "secret",
            "--wifi-ssid",
            "Network",
        ]
    )
    assert result.returncode != 0
    assert "--wifi-password is required" in result.stderr


def test_env_password_file(tmp_path):
    secret_file = tmp_path / "passphrase.txt"
    secret_file.write_text("env-secret\n", encoding="utf-8")
    output = tmp_path / "preset-env.json"
    env = os.environ.copy()
    env["SUGARKUBE_PRESET_SECRET_FILE"] = str(secret_file)
    result = run_preset(
        [
            "--hostname",
            "env-pi",
            "--username",
            "envuser",
            "--wifi-ssid",
            "EnvNet",
            "--wifi-password",
            "env-pass",
            "--output",
            str(output),
        ],
        env=env,
    )
    assert result.returncode == 0, result.stderr
    config = json.loads(output.read_text(encoding="utf-8"))["config"]
    assert config["password"].startswith("$6$")
