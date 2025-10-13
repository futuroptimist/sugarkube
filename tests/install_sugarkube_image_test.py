import hashlib
import json
import lzma
import os
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]


def run_install(args=None, env=None, cwd=None):
    cmd = ["/bin/bash", str(BASE_DIR / "scripts" / "install_sugarkube_image.sh")]
    if args:
        cmd.extend(args)
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd)


def create_gh_stub(bin_dir: Path) -> None:
    script = bin_dir / "gh"
    script.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
cmd="${1:-}"
if [ $# -gt 0 ]; then
  shift
fi
case "$cmd" in
  api)
    if [ -n "${GH_RELEASE_PAYLOAD:-}" ]; then
      printf '%s' "$GH_RELEASE_PAYLOAD"
      exit 0
    fi
    exit 1
    ;;
  auth)
    case "${1:-}" in
      token)
        echo "stub-gh-token"
        exit 0
        ;;
    esac
    ;;
esac
echo "unexpected gh call: $cmd $*" >&2
exit 1
"""
    )
    script.chmod(0o755)


def create_download_helper(script: Path) -> None:
    script.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

output=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output)
      output="$2"
      shift 2
      ;;
    *)
      shift || true
      ;;
  esac
done

if [ -z "$output" ]; then
  echo "missing --output" >&2
  exit 1
fi

python3 - "$output" <<'PYCODE'
import lzma
import os
import pathlib
import sys

dest = pathlib.Path(sys.argv[1])
dest.parent.mkdir(parents=True, exist_ok=True)
payload = os.environ.get("SUGARKUBE_TEST_PAYLOAD", "sugarkube-image").encode("utf-8")
with lzma.open(dest, "wb") as fh:
    fh.write(payload)
PYCODE

python3 - "$output" <<'PYCODE'
import hashlib
import pathlib
import sys

dest = pathlib.Path(sys.argv[1])
sha = hashlib.sha256(dest.read_bytes()).hexdigest()
checksum = dest.parent / (dest.name + ".sha256")
checksum.write_text(sha + '\\n')
PYCODE

if [ "${SKIP_HELPER_RUN_MARKER:-0}" -ne 1 ]; then
  printf '%s\n' "${SUGARKUBE_TEST_RUN_ID:-helper-run}" >"${output}.run"
fi
"""
    )
    script.chmod(0o755)


def make_release_payload(image: Path, checksum: Path) -> str:
    return json.dumps(
        {
            "tag_name": "v9.9.9",
            "assets": [
                {
                    "name": "sugarkube.img.xz",
                    "browser_download_url": f"file://{image}",
                },
                {
                    "name": "sugarkube.img.xz.sha256",
                    "browser_download_url": f"file://{checksum}",
                },
            ],
        }
    )


def test_install_dry_run_previews_actions(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.update({"HOME": str(tmp_path / "home")})

    result = run_install(
        args=["--dry-run", "--dir", str(tmp_path / "images")],
        env=env,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    stdout = result.stdout
    assert "Dry-run: would download" in stdout
    assert "Dry-run: would expand archive" in stdout
    assert not (tmp_path / "images").exists()


def test_install_downloads_and_expands(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    create_gh_stub(fake_bin)

    image_bytes = b"sugarkube" * 1024
    archive = tmp_path / "sugarkube.img.xz"
    with lzma.open(archive, "wb") as fh:
        fh.write(image_bytes)
    archive_bytes = archive.read_bytes()
    sha = hashlib.sha256(archive_bytes).hexdigest()
    checksum = tmp_path / "sugarkube.img.xz.sha256"
    checksum.write_text(f"{sha}\n")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "GH_RELEASE_PAYLOAD": make_release_payload(archive, checksum),
            "GH_TOKEN": "dummy",
            "GITHUB_TOKEN": "dummy",
            "HOME": str(tmp_path / "home"),
            "SUGARKUBE_INSTALL_HELPER": str(BASE_DIR / "scripts" / "download_pi_image.sh"),
            "SUGARKUBE_SKIP_GH_INSTALL": "0",
        }
    )

    result = run_install(env=env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr

    image_dir = Path(env["HOME"]) / "sugarkube" / "images"
    archive_path = image_dir / "sugarkube.img.xz"
    expanded = image_dir / "sugarkube.img"

    assert archive_path.read_bytes() == archive_bytes
    assert expanded.exists()
    assert expanded.read_bytes() == image_bytes
    checksum_path = Path(str(expanded) + ".sha256")
    assert checksum_path.exists()


def test_install_forwards_workflow_run(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh_stub = fake_bin / "gh"
    gh_stub.write_text("#!/usr/bin/env bash\nexit 0\n")
    gh_stub.chmod(0o755)

    helper_log = tmp_path / "helper_args.log"
    helper_script = tmp_path / "helper.sh"
    helper_script.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$@" >>"{helper_log}"
output=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output)
      output="$2"
      shift 2
      ;;
    *)
      shift || true
      ;;
  esac
done
if [ -n "$output" ]; then
  mkdir -p "$(dirname "$output")"
  echo stub-image >"$output"
  echo d41d8cd98f00b204e9800998ecf8427e  "$(basename "$output")" >"${{output}}.sha256"
fi
"""
    )
    helper_script.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "HOME": str(tmp_path / "home"),
            "SUGARKUBE_INSTALL_HELPER": str(helper_script),
        }
    )

    result = run_install(
        args=[
            "--workflow-run",
            "101",
            "--download-only",
            "--skip-gh-install",
            "--dir",
            str(tmp_path / "images"),
        ],
        env=env,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    logged_args = helper_log.read_text(encoding="utf-8")
    assert "--workflow-run" in logged_args
    assert "101" in logged_args


def test_install_propagates_workflow_run_marker(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    create_gh_stub(fake_bin)

    helper_script = tmp_path / "download_helper.sh"
    create_download_helper(helper_script)

    run_id = "4242"
    download_dir = tmp_path / "downloads"
    image_dir = tmp_path / "images"
    image_dest = image_dir / "sugarkube.img"

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "HOME": str(tmp_path / "home"),
            "SUGARKUBE_INSTALL_HELPER": str(helper_script),
            "SUGARKUBE_TEST_RUN_ID": run_id,
        }
    )

    result = run_install(
        args=[
            "--workflow-run",
            run_id,
            "--skip-gh-install",
            "--dir",
            str(download_dir),
            "--image",
            str(image_dest),
        ],
        env=env,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr

    archive = download_dir / "sugarkube.img.xz"
    archive_run = Path(str(archive) + ".run")
    image_run = Path(str(image_dest) + ".run")

    assert archive.exists()
    assert image_dest.exists()
    assert archive_run.read_text(encoding="utf-8").strip() == run_id
    assert image_run.read_text(encoding="utf-8").strip() == run_id


def test_install_synthesizes_run_marker_when_helper_skips(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    create_gh_stub(fake_bin)

    helper_script = tmp_path / "download_helper.sh"
    create_download_helper(helper_script)

    run_id = "5150"
    download_dir = tmp_path / "downloads"
    image_dir = tmp_path / "images"
    image_dest = image_dir / "sugarkube.img"

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "HOME": str(tmp_path / "home"),
            "SUGARKUBE_INSTALL_HELPER": str(helper_script),
            "SUGARKUBE_TEST_RUN_ID": run_id,
            "SKIP_HELPER_RUN_MARKER": "1",
        }
    )

    result = run_install(
        args=[
            "--workflow-run",
            run_id,
            "--skip-gh-install",
            "--dir",
            str(download_dir),
            "--image",
            str(image_dest),
        ],
        env=env,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr

    archive = download_dir / "sugarkube.img.xz"
    archive_run = Path(str(archive) + ".run")
    image_run = Path(str(image_dest) + ".run")

    assert archive.exists()
    assert image_dest.exists()
    assert archive_run.read_text(encoding="utf-8").strip() == run_id
    assert image_run.read_text(encoding="utf-8").strip() == run_id


def test_install_uses_custom_gh_hook(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    system_bin = tmp_path / "system"
    system_bin.mkdir()
    sentinel = tmp_path / "system-gh-used"
    system_gh = system_bin / "gh"
    system_gh.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
echo system-gh >\"{sentinel}\"
exit 42
"""
    )
    system_gh.chmod(0o755)

    image_bytes = b"hook" * 1024
    archive = tmp_path / "hook.img.xz"
    with lzma.open(archive, "wb") as fh:
        fh.write(image_bytes)
    archive_bytes = archive.read_bytes()
    sha = hashlib.sha256(archive_bytes).hexdigest()
    checksum = tmp_path / "hook.img.xz.sha256"
    checksum.write_text(f"{sha}\n")

    hook_script = tmp_path / "gh_hook.sh"
    hook_script.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
cat <<'EOF' >"${HOOK_DEST}/gh"
#!/usr/bin/env bash
set -euo pipefail
cmd="${1:-}"
if [ $# -gt 0 ]; then
  shift
fi
case "$cmd" in
  api)
    if [ -n "${GH_RELEASE_PAYLOAD:-}" ]; then
      printf '%s' "$GH_RELEASE_PAYLOAD"
      exit 0
    fi
    exit 1
    ;;
esac
echo "unexpected gh call: $cmd $*" >&2
exit 1
EOF
chmod +x "${HOOK_DEST}/gh"
"""
    )
    hook_script.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{system_bin}:{env['PATH']}",
            "GH_RELEASE_PAYLOAD": make_release_payload(archive, checksum),
            "HOOK_DEST": str(fake_bin),
            "SUGARKUBE_GH_INSTALL_HOOK": f". '{hook_script}'",
            "SUGARKUBE_INSTALL_HELPER": str(BASE_DIR / "scripts" / "download_pi_image.sh"),
            "HOME": str(tmp_path / "home"),
            "GITHUB_TOKEN": "dummy",
            "GH_TOKEN": "dummy",
        }
    )

    result = run_install(env=env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert (fake_bin / "gh").exists()
    assert not sentinel.exists()


def test_install_dry_run_previews_without_changes(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    create_gh_stub(fake_bin)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "HOME": str(tmp_path / "home"),
            "GITHUB_TOKEN": "dummy",
            "GH_TOKEN": "dummy",
            "SUGARKUBE_INSTALL_HELPER": str(BASE_DIR / "scripts" / "download_pi_image.sh"),
        }
    )

    preview_dir = tmp_path / "preview"
    result = run_install(args=["--dry-run", "--dir", str(preview_dir)], env=env, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "Dry-run" in result.stdout
    assert not preview_dir.exists()
    assert not (Path(env["HOME"]) / "sugarkube").exists()
