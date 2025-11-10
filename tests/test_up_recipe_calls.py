from pathlib import Path


def _extract_recipe(lines, header):
    collecting = False
    body = []
    indent = "    "
    for line in lines:
        if not collecting:
            if line.startswith(header):
                collecting = True
            continue
        if line and not line.startswith(indent):
            break
        body.append(line)
    return body


def test_up_recipe_runs_checks_and_discovery():
    lines = Path("justfile").read_text(encoding="utf-8").splitlines()
    body = _extract_recipe(lines, "up env='dev':")
    assert any("check_memory_cgroup.sh" in line for line in body)
    assert any("sudo -E bash scripts/k3s-discover.sh" in line for line in body)


def test_up_recipe_respects_save_debug_logs_toggle():
    lines = Path("justfile").read_text(encoding="utf-8").splitlines()
    body = _extract_recipe(lines, "up env='dev':")
    assert any("SAVE_DEBUG_LOGS" in line for line in body)
    assert any("capture_debug_log.py" in line for line in body)
