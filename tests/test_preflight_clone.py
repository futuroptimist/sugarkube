"""Tests for the SD to NVMe preflight helper."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_preflight_unmounts_mounted_partitions(tmp_path: Path) -> None:
    """The preflight helper should unmount mounted target partitions automatically."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    mount_state = tmp_path / "mount_state.txt"
    mount_state.write_text("mounted\n", encoding="utf-8")

    umount_log = tmp_path / "umount.log"

    target_device = tmp_path / "fake-target"
    target_device.touch()

    bash_env = tmp_path / "bypass-block-check.sh"
    bash_env.write_text(
        "function [ {\n"
        '  local args=("$@")\n'
        "  local last_index=$((${#args[@]} - 1))\n"
        "  if [[ ${args[$last_index]} == ']' ]]; then\n"
        "    unset 'args[$last_index]'\n"
        "  fi\n"
        "  if [[ ${args[0]} == '!' ]]; then\n"
        "    if [[ ${args[1]} == '-b' && ${args[2]} == \"$TARGET\" ]]; then\n"
        "      return 1\n"
        "    fi\n"
        '    builtin test "${args[@]}"\n'
        "    return $?\n"
        "  fi\n"
        "  if [[ ${args[0]} == '-b' && ${args[1]} == \"$TARGET\" ]]; then\n"
        "    return 0\n"
        "  fi\n"
        '  builtin test "${args[@]}"\n'
        "  return $?\n"
        "}\n",
        encoding="utf-8",
    )

    # Stub `findmnt` to report a safe root device path.
    _write_executable(
        bin_dir / "findmnt",
        (
            "#!/usr/bin/env bash\n"
            'if [ "$1" = "-no" ] && [ "$2" = "SOURCE" ] && [ "$3" = "/" ]; then\n'
            "  printf '/dev/mmcblk0p2\\n'\n"
            "  exit 0\n"
            "fi\n"
            "printf 'unexpected findmnt invocation: %s\\n' \"$*\" >&2\n"
            "exit 1\n"
        ),
    )

    # Stub `readlink -f` so the script can resolve fake device paths.
    _write_executable(
        bin_dir / "readlink",
        (
            "#!/usr/bin/env bash\n"
            'if [ "$1" = "-f" ]; then\n'
            "  printf '%s\\n' \"$2\"\n"
            "  exit 0\n"
            "fi\n"
            "printf '%s\\n' \"$1\"\n"
        ),
    )

    # Stub `lsblk` with minimal argument handling for the script's queries.
    _write_executable(
        bin_dir / "lsblk",
        (
            "#!/usr/bin/env python3\n"
            "import os\n"
            "import sys\n"
            "from pathlib import Path\n\n"
            "state_path = Path(os.environ['STUB_MOUNT_STATE'])\n"
            "target = Path(os.environ['STUB_TARGET'])\n"
            "args = sys.argv[1:]\n\n"
            "def _print(value: str = '') -> None:\n"
            '    sys.stdout.write(f"{value}\\n")\n\n'
            "if args[:2] == ['-no', 'pkname']:\n"
            "    device = args[2]\n"
            "    if device == '/dev/mmcblk0p2':\n"
            "        _print('mmcblk0')\n"
            "    else:\n"
            "        _print('')\n"
            "    sys.exit(0)\n\n"
            "if args[:3] == ['-nb', '-o', 'SIZE']:\n"
            "    _print('100000000000')\n"
            "    sys.exit(0)\n\n"
            "if args[:3] == ['-nr', '-o', 'NAME,MOUNTPOINT']:\n"
            "    device = Path(args[-1])\n"
            "    state = state_path.read_text(encoding='utf-8').strip()\n"
            "    if device == target:\n"
            "        name = target.name\n"
            "        if state == 'mounted':\n"
            "            _print(f'{name}p1 /mnt/clone1')\n"
            "            _print(f'{name}p2 /mnt/clone2')\n"
            "        else:\n"
            "            _print(f'{name}p1')\n"
            "            _print(f'{name}p2')\n"
            "    sys.exit(0)\n\n"
            "if args[:3] == ['-nr', '-o', 'NAME']:\n"
            "    device = Path(args[-1])\n"
            "    if device == target:\n"
            "        name = target.name\n"
            "        _print(name)\n"
            "        _print(f'{name}p1')\n"
            "        _print(f'{name}p2')\n"
            "    sys.exit(0)\n\n"
            "sys.stderr.write(f'unexpected lsblk invocation: {args!r}\\n')\n"
            "sys.exit(1)\n"
        ),
    )

    # Stub `blkid` for the PARTUUID lookup at the end of the script.
    _write_executable(
        bin_dir / "blkid",
        (
            "#!/usr/bin/env bash\n"
            'if [ "$1" = "-s" ] \\\n'
            '  && [ "$2" = "PARTUUID" ] \\\n'
            '  && [ "$3" = "-o" ] \\\n'
            '  && [ "$4" = "value" ]; then\n'
            "  printf '1234-ABCD\\n'\n"
            "  exit 0\n"
            "fi\n"
            "exit 0\n"
        ),
    )

    # Stub `wipefs` to report no existing signatures.
    _write_executable(
        bin_dir / "wipefs",
        (
            "#!/usr/bin/env bash\n"
            'if [ "$1" = "--noheadings" ]; then\n'
            "  exit 0\n"
            "fi\n"
            'if [ "$1" = "-a" ]; then\n'
            "  exit 0\n"
            "fi\n"
            "exit 0\n"
        ),
    )

    # Track unmount calls and mark the state file as unmounted.
    _write_executable(
        bin_dir / "umount",
        (
            "#!/usr/bin/env bash\n"
            'log_file="${STUB_UMOUNT_LOG}"\n'
            'state_file="${STUB_MOUNT_STATE}"\n'
            'printf \'%s\\n\' "$*" >>"${log_file}"\n'
            "printf 'unmounted\\n' >\"${state_file}\"\n"
            "exit 0\n"
        ),
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["TARGET"] = str(target_device)
    env["WIPE"] = "0"
    env["STUB_MOUNT_STATE"] = str(mount_state)
    env["STUB_UMOUNT_LOG"] = str(umount_log)
    env["STUB_TARGET"] = str(target_device)
    env["BASH_ENV"] = str(bash_env)

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "preflight_clone.sh"
    result = subprocess.run(
        ["bash", str(script_path)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "[ok] Target partitions unmounted" in combined
    log_lines = umount_log.read_text(encoding="utf-8").strip().splitlines()
    assert log_lines == ["/mnt/clone1", "/mnt/clone2"]
