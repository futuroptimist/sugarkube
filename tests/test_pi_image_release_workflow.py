from pathlib import Path
import re


WORKFLOW = Path(".github/workflows/pi-image-release.yml")
REQUIRED_INPUTS = {
    "release_channel",
    "clone_sugarkube",
    "clone_token_place",
    "clone_dspace",
    "publish_release",
    "run_qemu_smoke",
}


def _strip_comment(line: str) -> str:
    return line.split("#", 1)[0].rstrip()


def _top_level_on(lines: list[str]) -> tuple[int, str]:
    for index, line in enumerate(lines):
        match = re.match(
            r'^(?P<indent>\s*)(?:"on"|on)\s*:\s*(?P<value>.*)$',
            _strip_comment(line),
        )
        if match and not match.group("indent"):
            return index, match.group("value").strip()
    raise AssertionError("workflow must define a top-level on block")


def _on_entries(workflow: str) -> set[str]:
    lines = workflow.splitlines()
    index, value = _top_level_on(lines)
    entries: set[str] = set()
    if value:
        if value.startswith("[") and value.endswith("]"):
            entries.update(
                item.strip().strip("'\"") for item in value[1:-1].split(",")
            )
        else:
            entries.add(value.strip().strip("'\""))
        return {entry for entry in entries if entry}

    for line in lines[index + 1 :]:
        stripped = _strip_comment(line)
        if not stripped:
            continue
        if not line.startswith((" ", "\t")):
            break
        key_match = re.match(r'^\s+([A-Za-z0-9_-]+)\s*:', stripped)
        list_match = re.match(r'^\s+-\s*([A-Za-z0-9_-]+)\s*$', stripped)
        if key_match:
            entries.add(key_match.group(1))
        elif list_match:
            entries.add(list_match.group(1))
    return entries


def test_on_entry_parser_catches_compact_automatic_triggers() -> None:
    assert _on_entries("on: push\n") == {"push"}
    assert _on_entries("on: [push, workflow_dispatch]\n") == {
        "push",
        "workflow_dispatch",
    }
    assert _on_entries("on:\n  - schedule\n  - workflow_dispatch\n") == {
        "schedule",
        "workflow_dispatch",
    }


def test_release_workflow_is_manual_dispatch_only() -> None:
    workflow = WORKFLOW.read_text()
    triggers = _on_entries(workflow)
    assert "workflow_dispatch" in triggers
    assert "push" not in triggers
    assert "schedule" not in triggers


def test_release_workflow_declares_required_dispatch_inputs() -> None:
    workflow = WORKFLOW.read_text()
    for input_name in REQUIRED_INPUTS:
        assert re.search(rf"^\s{{6}}{input_name}:", workflow, re.MULTILINE)


def test_release_workflow_clones_sugarkube_by_default() -> None:
    workflow = WORKFLOW.read_text()
    assert re.search(
        r"^\s+clone_sugarkube:\n(?:\s+.*\n)*?\s+default: true",
        workflow,
        re.MULTILINE,
    )
    assert (
        "CLONE_SUGARKUBE: ${{ inputs.clone_sugarkube == false && 'false' || 'true' }}"
        in workflow
    )


def test_release_workflow_keeps_runner_and_cache_guards() -> None:
    workflow = WORKFLOW.read_text()
    assert "/opt/hostedtoolcache" not in workflow
    assert "Verify Node runtime availability" in workflow
    assert "scripts/compute_pi_gen_cache_key.sh" in workflow


def test_release_workflow_requires_qemu_smoke_for_publishing() -> None:
    workflow = WORKFLOW.read_text()
    assert "Validate release publishing inputs" in workflow
    assert "PUBLISH_RELEASE" in workflow
    assert "RUN_QEMU_SMOKE" in workflow
    assert "QEMU smoke evidence is required when publish_release=true" in workflow
    assert "if: env.PUBLISH_RELEASE != 'false'" in workflow
    assert "if: env.RUN_QEMU_SMOKE != 'false'" in workflow


def test_release_workflow_allows_validate_only_without_publishing() -> None:
    workflow = WORKFLOW.read_text()
    assert "publish_release:" in workflow
    assert "false validates without signing/publishing" in workflow
    assert "Install cosign" in workflow
    assert "Sign release artifacts" in workflow
    assert "Publish GitHub release" in workflow
    assert workflow.count("if: env.PUBLISH_RELEASE != 'false'") >= 3


def test_release_workflow_normalizes_checksum_to_relative_filename() -> None:
    workflow = WORKFLOW.read_text()
    assert "Normalize release checksum filename" in workflow
    assert "sha256sum sugarkube.img.xz" in workflow
    assert "sugarkube.img.xz" in workflow
    assert ">sugarkube.img.xz.sha256" in workflow
