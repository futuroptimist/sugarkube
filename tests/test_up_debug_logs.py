from pathlib import Path

from tests.test_up_recipe_calls import _extract_recipe


def test_up_recipe_supports_save_debug_logs() -> None:
    lines = Path("justfile").read_text(encoding="utf-8").splitlines()
    body = _extract_recipe(lines, "up env='dev':")
    assert any("SAVE_DEBUG_LOGS" in line for line in body)
    assert any("filter_debug_log.py" in line for line in body)
    assert any("SUGARKUBE_DEBUG_LOG_FILE" in line for line in body)
