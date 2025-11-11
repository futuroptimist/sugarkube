from pathlib import Path


def test_wipe_recipe_invokes_wrapper_script():
    justfile = Path("justfile").read_text(encoding="utf-8")
    lines = [line.strip() for line in justfile.splitlines()]

    expected = (
        "sudo --preserve-env=SUGARKUBE_CLUSTER,SUGARKUBE_ENV,DRY_RUN,ALLOW_NON_ROOT "
        "bash scripts/wipe_node.sh"
    )

    assert expected in lines, "wipe recipe should invoke wipe_node.sh via sudo"
    assert (
        "@" + expected not in lines
    ), "wipe recipe must not prefix sudo with @ inside script mode"
