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
