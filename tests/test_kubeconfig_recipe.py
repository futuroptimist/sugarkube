import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="kubeconfig recipe requires POSIX paths",
)


def write_stub_sudo(stub_dir: Path) -> Path:
    script = stub_dir / "sudo"
    script.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            set -eu
            cmd="$1"
            shift
            case "$cmd" in
              cp)
                if [ "$1" = "/etc/rancher/k3s/k3s.yaml" ]; then
                  shift
                  exec /bin/cp "${MOCK_ETC_RANCHER}/k3s.yaml" "$@"
                fi
                exec /bin/cp "$@"
                ;;
              chown)
                exit 0
                ;;
              *)
                exec "$cmd" "$@"
                ;;
            esac
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def write_stub_just(stub_dir: Path) -> Path:
    script = stub_dir / "just"
    script_lines = [
        "#!/usr/bin/env python3",
        "import os",
        "import subprocess",
        "import sys",
        "from pathlib import Path",
        "",
        "",
        "def main() -> None:",
        "    args = sys.argv[1:]",
        "    justfile = Path(\"justfile\")",
        "    recipe = None",
        "    env_value = \"dev\"",
        "    idx = 0",
        "    while idx < len(args):",
        "        arg = args[idx]",
        "        if arg == \"--justfile\":",
        "            idx += 1",
        "            justfile = Path(args[idx])",
        "        elif arg.startswith(\"env=\"):",
        "            env_value = arg.split(\"=\", 1)[1]",
        "        elif recipe is None:",
        "            recipe = arg",
        "        idx += 1",
        "",
        "    if recipe != \"kubeconfig\":",
        "        raise SystemExit(f\"unsupported recipe: {recipe}\")",
        "",
        "    lines = justfile.read_text(encoding=\"utf-8\").splitlines()",
        "    body: list[str] = []",
        "    capture = False",
        "    for line in lines:",
        "        if capture:",
        "            if line.startswith(\"    \"):",
        "                body.append(line.strip())",
        "            elif line.strip() == \"\" and body:",
        "                continue",
        "            else:",
        "                break",
        "        elif line.startswith(\"kubeconfig\"):",
        "            capture = True",
        "",
        "    if not body:",
        "        raise SystemExit(\"kubeconfig recipe not found\")",
        "",
        "    script_text = \"\\n\".join(body).replace(\"{{ env }}\", env_value)",
        "",
        "    completed = subprocess.run(",
        "        [\"bash\", \"-euo\", \"pipefail\", \"-c\", script_text],",
        "        env=os.environ.copy(),",
        "        check=False,",
        "    )",
        "    raise SystemExit(completed.returncode)",
        "",
        "",
        "if __name__ == \"__main__\":",
        "    main()",
        "",
    ]
    script.write_text("\n".join(script_lines), encoding="utf-8")
    script.chmod(0o755)
    return script


def test_kubeconfig_recipe_scopes_context(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]

    fake_home = tmp_path / "home"
    fake_home.mkdir()

    etc_dir = tmp_path / "etc" / "rancher" / "k3s"
    etc_dir.mkdir(parents=True)
    (etc_dir / "k3s.yaml").write_text(
        textwrap.dedent(
            """\
            apiVersion: v1
            clusters:
            - cluster:
                certificate-authority-data: ZHVtbXk=
                server: https://127.0.0.1:6443
              name: default
            contexts:
            - context:
                cluster: default
                namespace: default
                user: default
              name: default
            current-context: default
            kind: Config
            preferences: {}
            users:
            - name: default
              user:
                token: placeholder
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    write_stub_sudo(stub_dir)
    write_stub_just(stub_dir)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(fake_home),
            "PATH": f"{stub_dir}:{env['PATH']}",
            "MOCK_ETC_RANCHER": str(etc_dir),
            "USER": env.get("USER", "root"),
        }
    )

    result = subprocess.run(
        [
            "just",
            "--justfile",
            str(repo_root / "justfile"),
            "kubeconfig",
            "env=dev",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    config_path = fake_home / ".kube" / "config"
    assert config_path.exists(), "kubeconfig recipe should create ~/.kube/config"

    config_contents = config_path.read_text(encoding="utf-8")
    assert "name: sugar-dev" in config_contents
    assert "current-context: sugar-dev" in config_contents
