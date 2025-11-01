from pathlib import Path


def test_wipe_recipe_invokes_wrapper_script():
    justfile = Path("justfile").read_text(encoding="utf-8")
    assert (
        "@sudo --preserve-env=SUGARKUBE_CLUSTER,SUGARKUBE_ENV,DRY_RUN,ALLOW_NON_ROOT "
        "bash scripts/wipe_node.sh"
        in justfile
    )
