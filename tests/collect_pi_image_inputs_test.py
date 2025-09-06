import gzip
import os
import subprocess
import zipfile
from pathlib import Path


def _run_script(tmp_path, deploy, out_img, extra_env=None):
    env = os.environ.copy()
    env.update(extra_env or {})
    env["XZ_OPT"] = "-T0 -0"
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "collect_pi_image.sh"
    return subprocess.run(
        ["/bin/bash", str(script), str(deploy), str(out_img)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def test_handles_img_gz(tmp_path):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    img_gz = deploy / "foo.img.gz"
    with gzip.open(img_gz, "wb") as f:
        f.write(b"data")

    out_img = tmp_path / "out.img.xz"
    result = _run_script(tmp_path, deploy, out_img)
    assert result.returncode == 0, result.stderr
    assert out_img.exists()
    assert (out_img.with_suffix(out_img.suffix + ".sha256")).exists()


def test_errors_when_deploy_missing(tmp_path):
    deploy = tmp_path / "missing"
    out_img = tmp_path / "out.img.xz"
    result = _run_script(tmp_path, deploy, out_img)
    assert result.returncode != 0
    assert f"'{deploy}' does not exist" in result.stderr


def test_errors_on_zip_without_img(tmp_path):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    zip_path = deploy / "foo.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("readme.txt", "hello")

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

    out_img = tmp_path / "out.img.xz"
    result = _run_script(
        tmp_path,
        deploy,
        out_img,
        extra_env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert "Zip contained no .img" in result.stderr
