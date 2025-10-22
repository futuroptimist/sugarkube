from pathlib import Path


def test_up_recipe_calls_expected_scripts():
    lines = Path("justfile").read_text(encoding="utf-8").splitlines()
    target = "up env='dev': prereqs"
    assert target in lines
    start = lines.index(target) + 1
    body = []
    for line in lines[start:]:
        if line.strip() == "":
            body.append(line)
            continue
        if not line.startswith("    "):
            break
        body.append(line)

    block = "\n".join(body)
    assert "\"{{ scripts_dir }}/check_memory_cgroup.sh\"" in block
    assert "sudo -E bash scripts/k3s-discover.sh" in block
