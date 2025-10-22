from pathlib import Path


def test_wipe_recipe_shells_out():
    justfile = Path("justfile").read_text(encoding="utf-8")
    expected = (
        "wipe:\n"
        "    @sudo --preserve-env=SUGARKUBE_CLUSTER,SUGARKUBE_ENV,DRY_RUN,ALLOW_NON_ROOT bash scripts/wipe_node.sh"
    )
    assert expected in justfile
