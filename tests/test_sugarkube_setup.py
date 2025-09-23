import importlib.util
import io
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "sugarkube_setup.py"
SPEC = importlib.util.spec_from_file_location("scripts.sugarkube_setup", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("scripts.sugarkube_setup", MODULE)
SPEC.loader.exec_module(MODULE)  # type: ignore[arg-type]


class RecordingRunner:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def __call__(self, command, check=True, stdout=None, stderr=None, text=None):
        key = tuple(command)
        self.calls.append((key, stdout, stderr, text))
        outcome = self.mapping.get(
            key, subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        )
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_system_context_brew_helpers(tmp_path):
    runner = RecordingRunner(
        {
            ("brew", "tap"): subprocess.CompletedProcess(
                ["brew", "tap"], 0, stdout="homebrew/core\nsugarkube/sugarkube\n", stderr=""
            ),
            ("brew", "list", "--formula"): subprocess.CompletedProcess(
                ["brew", "list", "--formula"], 0, stdout="qemu\njust\n", stderr=""
            ),
            ("echo", "ok"): subprocess.CompletedProcess(["echo", "ok"], 0, stdout="", stderr=""),
        }
    )
    system = MODULE.SystemContext(runner=runner, home=tmp_path)
    assert MODULE.TAP_NAME in system.brew_taps()
    packages = system.brew_packages()
    assert {"qemu", "just"} <= packages

    created = system.ensure_directory(Path("sugarkube/images"))
    assert created.exists()

    wrote = system.write_config_file(Path("config/example.env"), "HELLO=1\n")
    assert wrote is True
    assert (tmp_path / "config/example.env").read_text() == "HELLO=1\n"

    wrote_again = system.write_config_file(Path("config/example.env"), "HELLO=2\n")
    assert wrote_again is False

    system.run(["echo", "ok"])


def test_system_context_run_text_errors(tmp_path):
    runner = RecordingRunner({("brew", "tap"): FileNotFoundError("missing brew")})
    system = MODULE.SystemContext(runner=runner, home=tmp_path)
    with pytest.raises(MODULE.SetupError) as excinfo:
        system.brew_taps()
    assert "Homebrew" in str(excinfo.value)

    failing_runner = RecordingRunner(
        {
            ("brew", "tap"): subprocess.CalledProcessError(
                1, ["brew", "tap"], stderr="tap list failed"
            )
        }
    )
    system = MODULE.SystemContext(runner=failing_runner, home=tmp_path)
    with pytest.raises(MODULE.SetupError) as excinfo:
        system.brew_taps()
    assert "tap list failed" in str(excinfo.value)

    run_runner = RecordingRunner(
        {
            ("brew", "install", "qemu"): subprocess.CalledProcessError(
                2, ["brew", "install", "qemu"], stderr="install failed"
            )
        }
    )
    system = MODULE.SystemContext(runner=run_runner, home=tmp_path)
    with pytest.raises(MODULE.SetupError) as excinfo:
        system.run(["brew", "install", "qemu"])
    assert "install failed" in str(excinfo.value)


class FakeSystem:
    def __init__(
        self,
        *,
        platform="darwin",
        has_brew=True,
        taps=None,
        packages=None,
        existing_paths=None,
        config_present=False,
    ):
        self._platform = platform
        self._has_brew = has_brew
        self._taps = set(taps or [])
        self._packages = set(packages or [])
        self._paths = set(existing_paths or [])
        self.home = Path("/Users/tester")
        self.commands: list[list[str]] = []
        self.created: list[Path] = []
        self._config_present = config_present
        self.rendered_config: str | None = None

    def platform(self):
        return self._platform

    def has_command(self, name):
        return self._has_brew if name == "brew" else True

    def brew_taps(self):
        return set(self._taps)

    def brew_packages(self):
        return set(self._packages)

    def path_exists(self, relative):
        return relative in self._paths

    def ensure_directory(self, relative):
        self._paths.add(relative)
        self.created.append(relative)
        return self.home / relative

    def write_config_file(self, relative, content):
        self.rendered_config = content
        if self._config_present:
            return False
        self._config_present = True
        return True

    def run(self, command):
        self.commands.append(list(command))
        if command[0] == "brew" and command[1] == "install":
            self._packages.add(command[2])
        if command[0] == "brew" and command[1] == "tap":
            self._taps.add(command[2])


def test_build_plan_requires_macos():
    system = FakeSystem(platform="linux")
    wizard = MODULE.SetupWizard(system, stream=io.StringIO())
    with pytest.raises(MODULE.SetupError):
        wizard.build_plan(force=False)


def test_build_plan_missing_dependencies():
    system = FakeSystem(taps=[], packages={"xz"}, existing_paths=set())
    wizard = MODULE.SetupWizard(system, stream=io.StringIO())
    plan = wizard.build_plan(force=False)
    descriptions = [task.description for task in plan]
    assert any("Add the" in desc and MODULE.TAP_NAME in desc for desc in descriptions)
    assert any(desc.startswith("Install qemu") for desc in descriptions)
    assert any(desc.startswith("Install the sugarkube") for desc in descriptions)
    assert any("Create" in desc for desc in descriptions)
    assert system.rendered_config is not None


def test_build_plan_force_non_macos():
    system = FakeSystem(platform="linux")
    wizard = MODULE.SetupWizard(system, stream=io.StringIO())
    plan = wizard.build_plan(force=True)
    assert plan[-1].description.startswith("Review docs/")


def test_build_plan_up_to_date():
    paths = {Path("sugarkube/images"), Path("sugarkube/reports"), Path("sugarkube/cache")}
    system = FakeSystem(
        taps={MODULE.TAP_NAME},
        packages=set(MODULE.REQUIRED_FORMULAE) | {"sugarkube"},
        existing_paths=paths,
        config_present=True,
    )
    wizard = MODULE.SetupWizard(system, stream=io.StringIO())
    plan = wizard.build_plan(force=False)
    assert len(plan) == 1
    assert "Review" in plan[0].description


def test_apply_executes_actions():
    system = FakeSystem(taps=[], packages=set())
    wizard = MODULE.SetupWizard(system, stream=io.StringIO())
    plan = wizard.build_plan(force=False)
    wizard.apply(plan)
    assert [cmd[:3] for cmd in system.commands if cmd[0] == "brew"]


def test_run_with_apply_executes(monkeypatch):
    system = FakeSystem(taps=[], packages=set())
    buffer = io.StringIO()
    wizard = MODULE.SetupWizard(system, stream=buffer)
    wizard.run(force=False, apply=True)
    output = buffer.getvalue()
    assert "Applying macOS setup actions" in output
    assert system.commands


def test_render_plan_empty():
    system = FakeSystem(
        taps={MODULE.TAP_NAME},
        packages={"sugarkube"} | set(MODULE.REQUIRED_FORMULAE),
    )
    wizard = MODULE.SetupWizard(system, stream=io.StringIO())
    wizard.build_plan(force=False)
    buffer = io.StringIO()
    wizard.stream = buffer
    wizard.render_plan([])
    assert "prerequisites" in buffer.getvalue()


def test_main_handles_error(capsys):
    system = FakeSystem(has_brew=False)
    exit_code = MODULE.main(["--apply"], system=system)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Install Homebrew" in captured.err


def test_run_without_apply_prompts(tmp_path):
    paths = {Path("sugarkube/images"), Path("sugarkube/reports"), Path("sugarkube/cache")}
    system = FakeSystem(
        taps={MODULE.TAP_NAME},
        packages=set(MODULE.REQUIRED_FORMULAE) | {"sugarkube"},
        existing_paths=paths,
        config_present=True,
    )
    buffer = io.StringIO()
    wizard = MODULE.SetupWizard(system, stream=buffer)
    exit_code = wizard.run(force=False, apply=False)
    assert exit_code == 0
    output = buffer.getvalue()
    assert "Re-run with --apply" in output
