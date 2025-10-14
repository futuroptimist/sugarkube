import os
import subprocess
import zipfile
from pathlib import Path


def test_collect_cleans_tmpdir(tmp_path):
    # Prepare deploy directory with a zip containing an image
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    img = deploy / "foo.img"
    img.write_text("data")
    zip_path = deploy / "foo.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(img, arcname=img.name)
    img.unlink()

    # Fake bsdtar to extract zip files
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    bsdtar = fake_bin / "bsdtar"
    bsdtar.write_text(
        "#!/bin/bash\n"
        'python - <<\'PY\' "$2" "$4"\n'
        "import sys, zipfile\n"
        "zip_path, dest = sys.argv[1:3]\n"
        "with zipfile.ZipFile(zip_path) as zf:\n"
        "    zf.extractall(dest)\n"
        "PY\n"
    )
    bsdtar.chmod(0o755)

    # Use dedicated TMPDIR to track temporary directories
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["TMPDIR"] = str(tmpdir)
    env["XZ_OPT"] = "-T0 -0"

    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "collect_pi_image.sh"
    out_img = tmp_path / "out.img.xz"

    result = subprocess.run(
        ["/bin/bash", str(script), str(deploy), str(out_img)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert out_img.exists()
    subprocess.run(
        ["sha256sum", "-c", out_img.name + ".sha256"],
        check=True,
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # After the script completes, TMPDIR should be empty
    assert not any(tmpdir.iterdir())
