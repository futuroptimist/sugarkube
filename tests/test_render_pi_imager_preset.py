import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "render_pi_imager_preset.py"
MODULE_SPEC = importlib.util.spec_from_file_location("render_pi_imager_preset", MODULE_PATH)
MODULE = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC and MODULE_SPEC.loader  # narrow types for mypy/pyright
MODULE_SPEC.loader.exec_module(MODULE)  # type: ignore[union-attr]

parse_key_value_file = MODULE.parse_key_value_file


def test_parse_key_value_file_strips_inline_comments(tmp_path: Path) -> None:
    secrets_path = tmp_path / "secrets.env"
    secrets_path.write_text(
        "\n".join(
            [
                'PI_PASSWORD="supers3cret"  # optional; hashes automatically',
                'WIFI_SSID="Cafe #1"  # keep the hash in quotes',
                "PLAIN=value-without-quotes  # trailing comment",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    secrets = parse_key_value_file(secrets_path)

    assert secrets["PI_PASSWORD"] == "supers3cret"
    assert secrets["WIFI_SSID"] == "Cafe #1"
    assert secrets["PLAIN"] == "value-without-quotes"
