#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def replace_line(lines: list[str], idx: int, key: str, value: str) -> None:
    prefix = lines[idx].split(f"{key}:")[0]
    lines[idx] = f"{prefix}{key}: {value}"


def main(config_path: Path, target: str) -> None:
    lines = config_path.read_text().splitlines()
    section: str | None = None

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("clusters:"):
            section = "clusters"
            continue
        if stripped.startswith("contexts:"):
            section = "contexts"
            continue
        if stripped.startswith("users:"):
            section = "users"
            continue
        if stripped.startswith("current-context:"):
            replace_line(lines, idx, "current-context", target)
            continue
        if not line.startswith(" ") and not line.startswith("-"):
            section = None
            continue

        name_in_section = stripped.startswith("name:") or stripped.startswith("- name:")

        if section == "clusters" and name_in_section:
            replace_line(lines, idx, "name", target)
        elif section == "contexts":
            if name_in_section:
                replace_line(lines, idx, "name", target)
            elif stripped.startswith("cluster:"):
                replace_line(lines, idx, "cluster", target)
            elif stripped.startswith("user:"):
                replace_line(lines, idx, "user", target)
        elif section == "users" and name_in_section:
            replace_line(lines, idx, "name", target)

    config_path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: update_kubeconfig_scope.py <config> <target>")
    main(Path(sys.argv[1]), sys.argv[2])
