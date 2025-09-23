#!/usr/bin/env python3
"""Desktop notifications when GitHub workflow artifacts are ready."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass
from typing import Callable, List, Mapping, Optional, Sequence


class WorkflowNotifierError(RuntimeError):
    """Raised when workflow notification encounters an unexpected failure."""


class NotificationUnavailableError(RuntimeError):
    """Raised when the platform notification backend cannot run."""


@dataclass(frozen=True)
class WorkflowReference:
    """Identifies a GitHub Actions workflow run."""

    repo: str
    run_id: int


def _parse_run_url(url: str) -> WorkflowReference:
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise WorkflowNotifierError("workflow URL must include scheme and host")
    path = parsed.path.strip("/")
    parts = path.split("/")
    if len(parts) < 5:
        raise WorkflowNotifierError("workflow URL must include /owner/repo/actions/runs/<id>")
    if parts[2] != "actions" or parts[3] != "runs":
        raise WorkflowNotifierError("workflow URL must include /actions/runs/<id>")
    owner = parts[0]
    repo_name = parts[1]
    run_id_text = parts[4]
    try:
        run_id = int(run_id_text)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise WorkflowNotifierError("workflow run id must be an integer") from exc
    return WorkflowReference(repo=f"{owner}/{repo_name}", run_id=run_id)


def _resolve_reference(args: argparse.Namespace) -> WorkflowReference:
    if args.run_url:
        return _parse_run_url(args.run_url)
    repo = args.repo or args.default_repo
    if not repo:
        raise WorkflowNotifierError("--repo is required when --run-url is not provided")
    if args.run_id is None:
        raise WorkflowNotifierError("--run-id is required when --run-url is not provided")
    try:
        run_id = int(str(args.run_id))
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise WorkflowNotifierError("--run-id must be an integer") from exc
    return WorkflowReference(repo=repo, run_id=run_id)


def _detect_platform() -> str:
    platform = sys.platform
    if platform.startswith("darwin"):
        return "macos"
    if platform.startswith("win"):
        return "windows"
    return "linux"


def _run_command(command: Sequence[str]) -> None:
    subprocess.run(command, check=True)


class SystemNotifier:
    """Send notifications using the active desktop environment."""

    def __init__(
        self,
        *,
        platform: Optional[str] = None,
        runner: Optional[Callable[[Sequence[str]], None]] = None,
    ) -> None:
        self._platform = platform or _detect_platform()
        self._runner = runner or _run_command

    @staticmethod
    def _linux_command(title: str, body: str, url: Optional[str]) -> List[str]:
        command = [
            "notify-send",
            "--app-name",
            "sugarkube",
            title,
            body if not url else f"{body}\n{url}",
        ]
        return command

    @staticmethod
    def _macos_command(title: str, body: str, url: Optional[str]) -> List[str]:
        message = body if not url else f"{body}\n{url}"
        script = "display notification " f"{json.dumps(message)} with title {json.dumps(title)}"
        return ["osascript", "-e", script]

    @staticmethod
    def _windows_command(title: str, body: str, url: Optional[str]) -> List[str]:
        payload = json.dumps(
            {
                "title": title,
                "message": body if not url else f"{body}\n{url}",
            }
        ).replace("'", "''")
        script = (
            "$payload = ConvertFrom-Json @'"
            f"{payload}"
            "'@;"
            "Add-Type -AssemblyName System.Windows.Forms;"
            "[System.Windows.Forms.MessageBox]::Show($payload.message, $payload.title)"
            " | Out-Null;"
        )
        return ["powershell", "-NoLogo", "-NoProfile", "-Command", script]

    def notify(self, *, title: str, body: str, url: Optional[str]) -> None:
        if self._platform == "macos":
            command = self._macos_command(title, body, url)
        elif self._platform == "windows":
            command = self._windows_command(title, body, url)
        else:
            command = self._linux_command(title, body, url)
        try:
            self._runner(command)
        except FileNotFoundError as exc:  # pragma: no cover - depends on host
            raise NotificationUnavailableError(
                f"notification command not found for platform {self._platform}"
            ) from exc
        except subprocess.CalledProcessError as exc:  # pragma: no cover - external failure
            raise NotificationUnavailableError("notification command failed") from exc


class ConsoleNotifier:
    """Fallback notifier that prints messages to stdout."""

    def notify(self, *, title: str, body: str, url: Optional[str]) -> None:
        print(title)
        print(body)
        if url:
            print(url)


class GhClient:
    """Wrapper around `gh api` so we can stub calls during testing."""

    def __init__(self, executable: str) -> None:
        self._executable = executable

    def _api(self, path: str) -> Mapping[str, object]:
        command = [
            self._executable,
            "api",
            path,
            "--header",
            "Accept: application/vnd.github+json",
        ]
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise WorkflowNotifierError(
                f"unable to execute '{self._executable}'. Install GitHub CLI (gh) first."
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise WorkflowNotifierError(f"gh api failed: {exc.stderr or exc}") from exc
        try:
            return json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:  # pragma: no cover - gh contract
            raise WorkflowNotifierError("gh api returned invalid JSON") from exc

    def fetch_run(self, reference: WorkflowReference) -> Mapping[str, object]:
        return self._api(f"/repos/{reference.repo}/actions/runs/{reference.run_id}")

    def fetch_artifacts(self, reference: WorkflowReference) -> Sequence[Mapping[str, object]]:
        data = self._api(f"/repos/{reference.repo}/actions/runs/{reference.run_id}/artifacts")
        artifacts = data.get("artifacts", [])
        if not isinstance(artifacts, list):  # pragma: no cover - contract guard
            raise WorkflowNotifierError("unexpected gh api response for artifacts")
        return artifacts


class WorkflowWatcher:
    """Polls GitHub until a workflow run completes and exposes artifacts."""

    def __init__(
        self,
        client: GhClient,
        reference: WorkflowReference,
        *,
        poll_interval: float,
        timeout: Optional[float],
    ) -> None:
        self._client = client
        self._reference = reference
        self._poll_interval = poll_interval
        self._timeout = timeout

    def wait_for_artifacts(self) -> tuple[Mapping[str, object], Sequence[Mapping[str, object]]]:
        start = time.monotonic()
        while True:
            run = self._client.fetch_run(self._reference)
            status = run.get("status")
            if status == "completed":
                artifacts = self._client.fetch_artifacts(self._reference)
                return run, artifacts
            if self._timeout is not None and (time.monotonic() - start) > self._timeout:
                raise WorkflowNotifierError("timed out waiting for workflow run to complete.")
            time.sleep(self._poll_interval)


def _format_size(size_in_bytes: Optional[int]) -> str:
    if not size_in_bytes:
        return "unknown"
    kb = size_in_bytes / 1024
    if kb < 1024:
        return f"{kb:.1f} KiB"
    mb = kb / 1024
    return f"{mb:.1f} MiB"


def _summarize_artifacts(artifacts: Sequence[Mapping[str, object]]) -> List[str]:
    if not artifacts:
        return ["Artifacts: none available"]
    lines: List[str] = ["Artifacts:"]
    for artifact in artifacts:
        name = str(artifact.get("name", "unknown"))
        size = _format_size(int(artifact.get("size_in_bytes", 0) or 0))
        expired = artifact.get("expired", False)
        status = "expired" if expired else "ready"
        lines.append(f"  - {name} ({size}, {status})")
    return lines


def _build_message(
    run: Mapping[str, object],
    artifacts: Sequence[Mapping[str, object]],
) -> tuple[str, str]:
    run_number = run.get("run_number")
    conclusion = run.get("conclusion", "unknown")
    title = f"Sugarkube workflow #{run_number} {conclusion}" if run_number else "Sugarkube workflow"
    lines: List[str] = []
    if conclusion:
        lines.append(f"Conclusion: {conclusion}")
    head_commit = run.get("head_branch")
    if head_commit:
        lines.append(f"Branch: {head_commit}")
    event = run.get("event")
    if event:
        lines.append(f"Event: {event}")
    lines.extend(_summarize_artifacts(artifacts))
    body = "\n".join(lines)
    return title, body


def _parse_arguments(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-url", help="GitHub Actions run URL")
    parser.add_argument("--repo", help="owner/repo for the workflow run")
    parser.add_argument("--run-id", help="workflow run identifier")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=30.0,
        help="Seconds between gh api calls",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=900.0,
        help="Max seconds to wait; 0 disables",
    )
    parser.add_argument("--gh", default="gh", help="Path to the GitHub CLI executable")
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print messages instead of invoking system notifications",
    )
    parser.add_argument(
        "--platform",
        choices=["linux", "macos", "windows"],
        help="Override platform detection (testing)",
    )
    args = parser.parse_args(argv)
    if args.timeout is not None and args.timeout <= 0:
        args.timeout = None
    args.default_repo = os.environ.get("GITHUB_REPOSITORY")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_arguments(argv)
    try:
        reference = _resolve_reference(args)
    except WorkflowNotifierError as exc:
        raise SystemExit(str(exc)) from exc
    client = GhClient(args.gh)
    watcher = WorkflowWatcher(
        client,
        reference,
        poll_interval=args.poll_interval,
        timeout=args.timeout,
    )
    try:
        run, artifacts = watcher.wait_for_artifacts()
    except WorkflowNotifierError as exc:
        raise SystemExit(str(exc)) from exc
    title, body = _build_message(run, artifacts)
    url = run.get("html_url")
    if args.print_only:
        ConsoleNotifier().notify(title=title, body=body, url=url if isinstance(url, str) else None)
        return 0
    notifier = SystemNotifier(platform=args.platform)
    try:
        notifier.notify(
            title=title,
            body=body,
            url=url if isinstance(url, str) else None,
        )
    except NotificationUnavailableError as exc:
        ConsoleNotifier().notify(title=title, body=body, url=url if isinstance(url, str) else None)
        print(f"warning: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
