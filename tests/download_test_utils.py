import hashlib
import json
import lzma
import os
from pathlib import Path


def download_script_path() -> Path:
    return Path(__file__).resolve().parents[1] / "scripts" / "download_pi_image.sh"


def latest_script_path() -> Path:
    return Path(__file__).resolve().parents[1] / "scripts" / "sugarkube_latest.sh"


def write_stub_scripts(
    tmp_path: Path,
    *,
    asset_name: str = "sugarkube.img.xz",
    include_checksum: bool = True,
    checksum_entries: list[tuple[str, str]] | None = None,
) -> dict:
    """Create fake gh and curl binaries for exercising download helpers."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    raw_payload = b"sugarkube-image" * 4
    compressed_src = tmp_path / "source.img.xz"
    compressed_src.write_bytes(lzma.compress(raw_payload))

    sha_src = tmp_path / "source.sha256"
    digest = hashlib.sha256(compressed_src.read_bytes()).hexdigest()
    entries = checksum_entries if checksum_entries is not None else [(asset_name, digest)]
    sha_lines = [f"{entry_digest}  {entry_name}" for entry_name, entry_digest in entries]
    sha_src.write_text("\n".join(sha_lines) + "\n")

    image_url = "https://example.com/image"
    checksum_url = "https://example.com/image.sha"

    assets = [
        {
            "name": asset_name,
            "browser_download_url": image_url,
        }
    ]
    if include_checksum:
        assets.append(
            {
                "name": f"{asset_name}.sha256",
                "browser_download_url": checksum_url,
            }
        )

    release_json = json.dumps({"tag_name": "v0.0.1", "assets": assets})

    gh = bin_dir / "gh"
    gh.write_text(
        "#!/bin/bash\n"
        "set -e\n"
        'if [ "$1" = api ]; then\n'
        '  if [ "$2" = "repos/futuroptimist/sugarkube/releases/latest" ]; then\n'
        "    cat <<'JSON'\n"
        f"{release_json}\n"
        "JSON\n"
        "    exit 0\n"
        "  fi\n"
        'elif [ "$1" = auth ] && [ "$2" = token ]; then\n'
        '  if [ -n "${GH_TOKEN_OUTPUT:-}" ]; then\n'
        '    echo "$GH_TOKEN_OUTPUT"\n'
        "  else\n"
        "    echo FAKE_TOKEN\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    )
    gh.chmod(0o755)

    curl = bin_dir / "curl"
    curl.write_text(
        "#!/bin/bash\n"
        "set -e\n"
        'dest=""\n'
        'url=""\n'
        "while [ $# -gt 0 ]; do\n"
        '  case "$1" in\n'
        "    --output|-o) dest=$2; shift 2 ;;\n"
        "    --continue-at) shift 2 ;;\n"
        "    --retry|--retry-delay|--retry-max-time) shift 2 ;;\n"
        "    -H) shift 2 ;;\n"
        "    --fail|--location|--progress-bar) shift ;;\n"
        "    *) url=$1; shift ;;\n"
        "  esac\n"
        "done\n"
        'if [ -z "$dest" ]; then\n'
        '  echo "missing destination" >&2\n'
        "  exit 96\n"
        "fi\n"
        'case "$url" in\n'
        "  $IMAGE_URL)\n"
        '    if [ -n "$BLOCK_IMAGE_DOWNLOAD" ]; then\n'
        '      if [ -n "$IMAGE_MARKER" ]; then\n'
        '        echo attempted > "$IMAGE_MARKER"\n'
        "      fi\n"
        "      exit ${FAIL_IMAGE_DOWNLOAD:-1}\n"
        "    fi\n"
        '    cp "$IMAGE_SOURCE" "$dest"\n'
        '    if [ -n "$IMAGE_MARKER" ]; then\n'
        '      echo success > "$IMAGE_MARKER"\n'
        "    fi\n"
        "    ;;\n"
        "  $SHA_URL)\n"
        '    if [ -n "$FAIL_CHECKSUM_DOWNLOAD" ]; then\n'
        "      exit $FAIL_CHECKSUM_DOWNLOAD\n"
        "    fi\n"
        '    cp "$SHA_SOURCE" "$dest"\n'
        "    ;;\n"
        "  *)\n"
        '    echo "unexpected url: $url" >&2\n'
        "    exit ${CURL_UNEXPECTED_EXIT:-1}\n"
        "    ;;\n"
        "esac\n"
    )
    curl.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["IMAGE_SOURCE"] = str(compressed_src)
    env["SHA_SOURCE"] = str(sha_src)
    env["IMAGE_URL"] = image_url
    env["SHA_URL"] = checksum_url

    return env
