def test_errors_when_no_image_found(tmp_path):  # noqa: F811
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / "note.txt").write_text("no artifact")

    out_img = tmp_path / "out.img.xz"
    result = _run_script(tmp_path, deploy, out_img)
    assert result.returncode != 0
    assert "No image file found" in result.stderr


def test_succeeds_when_realpath_missing(tmp_path):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    img_xz = deploy / "foo.img.xz"
    img_xz.write_text("original")

    out_img = tmp_path / "out.img.xz"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_realpath = fake_bin / "realpath"
    fake_realpath.write_text(
        "#!/bin/sh\n"
        "echo realpath should not be invoked >&2\n"
        "exit 1\n"
    )
    fake_realpath.chmod(0o755)

    result = _run_script(
        tmp_path,
        deploy,
        out_img,
        extra_env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert out_img.exists()
