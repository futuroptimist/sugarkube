import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
PRESET_DIR = BASE_DIR / "docs" / "pi_imager_presets"

REQUIRED_CONFIG_KEYS = {
    "hostname",
    "username",
    "timezone",
    "ssh",
    "services",
    "run",
}


def test_presets_are_valid_json():
    presets = list(PRESET_DIR.glob("*.json"))
    assert presets, "expected at least one preset JSON"
    for preset in presets:
        data = json.loads(preset.read_text(encoding="utf-8"))
        assert data.get("schema_version") == 1
        assert "description" in data
        assert "config" in data
        config = data["config"]
        assert REQUIRED_CONFIG_KEYS.issubset(config.keys())
        ssh = config["ssh"]
        assert ssh.get("enabled") is True
        keys = ssh.get("authorized_keys") or []
        assert keys, "authorized_keys should provide a placeholder"
        assert any("REPLACE_WITH" in key for key in keys)
        run_cmds = config["run"]
        assert any("pi_node_verifier.sh" in cmd for cmd in run_cmds)


def test_readme_lists_presets():
    readme = (PRESET_DIR / "README.md").read_text(encoding="utf-8")
    for preset in PRESET_DIR.glob("*.json"):
        assert preset.name in readme
