"""Isolated filesystem ancestry for root-run network-helper tests."""

import os
from pathlib import Path

import pytest


@pytest.fixture
def trusted_network_test_ancestry(tmp_path, monkeypatch, enable_subprocess_coverage):
    """Keep production root checks strict; model trusted ancestors only in children."""

    def install(synthetic_root=False):
        shim = tmp_path / "python-test-ancestry"
        shim.mkdir(exist_ok=True)
        original_site = Path(__file__).resolve().parents[2] / "sitecustomize.py"
        (shim / "sitecustomize.py").write_text(
            "import os, runpy\n"
            "from pathlib import Path\n"
            f"runpy.run_path({str(original_site)!r})\n"
            f"fixture = Path({str(tmp_path)!r})\n"
            "ancestors = set(fixture.parents)\n"
            "original_lstat = Path.lstat\n"
            f"synthetic_root = {synthetic_root!r}\n"
            "def fixture_stat(path, *args, **kwargs):\n"
            "    values = list(original_lstat(path, *args, **kwargs))\n"
            "    if path in ancestors:\n"
            "        values[0] &= ~0o022\n"
            "        values[4] = 0\n"
            "    elif synthetic_root and path.is_relative_to(fixture):\n"
            "        values[4] = 0\n"
            "    return os.stat_result(values)\n"
            "Path.lstat = fixture_stat\n"
            "if synthetic_root:\n"
            "    os.geteuid = lambda: 0\n"
        )
        pythonpath = os.environ.get("PYTHONPATH", "")
        monkeypatch.setenv("PYTHONPATH", str(shim) + os.pathsep + pythonpath)
        original_lstat = Path.lstat
        ancestors = set(tmp_path.parents)

        def fixture_stat(path, *args, **kwargs):
            values = list(original_lstat(path, *args, **kwargs))
            if path in ancestors:
                values[0] &= ~0o022
                values[4] = 0
            elif synthetic_root and path.is_relative_to(tmp_path):
                values[4] = 0
            return os.stat_result(values)

        monkeypatch.setattr(Path, "lstat", fixture_stat)
        if synthetic_root:
            monkeypatch.setattr(os, "geteuid", lambda: 0)
        return os.environ["PYTHONPATH"]

    return install


@pytest.fixture(autouse=True)
def root_network_test_ancestry(request, trusted_network_test_ancestry):
    if os.geteuid() == 0 and request.path.name in {
        "test_k3s_discover_node_ip_binding.py",
        "test_detect_node_ip.py",
    }:
        trusted_network_test_ancestry(synthetic_root=True)
