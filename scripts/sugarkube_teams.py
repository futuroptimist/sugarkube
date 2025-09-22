#!/usr/bin/env python3
"""Optional webhook notifications for sugarkube automation."""

from __future__ import annotations

import argparse
import html
import json
import os
import random
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence

DEFAULT_ENV_PATH = Path("/etc/sugarkube/teams-webhook.env")
DEFAULT_TIMEOUT = 10.0
STATUS_EMOJIS = {
    "starting": "\u23f3",  # hourglass
    "success": "\u2705",  # white heavy check mark
    "failed": "\u274c",  # cross mark
    "info": "\u2139\ufe0f",  # information source
}
EVENT_LABELS = {
    "first-boot": "first boot",
    "ssd-clone": "SSD clone",
}


class TeamsNotificationError(RuntimeError):
    """Raised when webhook notification fails."""


@dataclass
class TeamsConfig:
    enable: bool
    url: str
    kind: str
    timeout: float
    verify_tls: bool
    username: Optional[str]
    icon: Optional[str]
    matrix_room: Optional[str]
    auth_credential: Optional[str]


def _env_flag(value: Optional[str], *, default: bool = False) -> bool:
    if value is None:
        return default
    value = value.strip().lower()
    return value in {"1", "true", "yes", "on"}


def _parse_env_file(path: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not path.exists():
        return data
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - unexpected IO failure
        raise TeamsNotificationError(f"unable to read {path}: {exc}") from exc
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        data[key] = value
    return data


def _get_config_value(
    key: str,
    *,
    env: Mapping[str, str],
    file_data: Mapping[str, str],
    default: Optional[str] = None,
) -> Optional[str]:
    if key in env:
        return env[key]
    return file_data.get(key, default)


def load_config(env: Mapping[str, str] | None = None) -> TeamsConfig:
    environ = env if env is not None else os.environ
    env_path_text = environ.get("SUGARKUBE_TEAMS_ENV", str(DEFAULT_ENV_PATH))
    env_path = Path(env_path_text)
    file_data = _parse_env_file(env_path)

    def fetch(key: str, default: Optional[str] = None) -> Optional[str]:
        return _get_config_value(key, env=environ, file_data=file_data, default=default)

    enable = _env_flag(fetch("SUGARKUBE_TEAMS_ENABLE"), default=False)
    url = (fetch("SUGARKUBE_TEAMS_URL") or "").strip()
    kind = (fetch("SUGARKUBE_TEAMS_KIND", "slack") or "slack").strip().lower()
    timeout_text = fetch("SUGARKUBE_TEAMS_TIMEOUT")
    timeout = DEFAULT_TIMEOUT
    if timeout_text:
        try:
            timeout = float(timeout_text)
        except ValueError as exc:
            raise TeamsNotificationError("SUGARKUBE_TEAMS_TIMEOUT must be a number") from exc
    verify_tls = _env_flag(fetch("SUGARKUBE_TEAMS_VERIFY_TLS"), default=True)
    username = fetch("SUGARKUBE_TEAMS_USERNAME")
    icon = fetch("SUGARKUBE_TEAMS_ICON")
    matrix_room = fetch("SUGARKUBE_TEAMS_MATRIX_ROOM")
    auth_credential = fetch("SUGARKUBE_TEAMS_TOKEN")

    return TeamsConfig(
        enable=enable,
        url=url,
        kind=kind,
        timeout=timeout,
        verify_tls=verify_tls,
        username=username if username else None,
        icon=icon if icon else None,
        matrix_room=matrix_room if matrix_room else None,
        auth_credential=auth_credential if auth_credential else None,
    )


def _format_heading(event: str, status: str) -> str:
    label = EVENT_LABELS.get(event, event.replace("-", " "))
    emoji = STATUS_EMOJIS.get(status, "")
    status_text = status.replace("_", " ").title()
    if emoji:
        return f"{emoji} Sugarkube {label} — {status_text}"
    return f"Sugarkube {label} — {status_text}"


def _build_plaintext(heading: str, lines: Sequence[str]) -> str:
    body = "\n".join(line.rstrip() for line in lines if line)
    if body:
        return f"{heading}\n{body}"
    return heading


def _build_html(heading: str, lines: Sequence[str], fields: Mapping[str, str]) -> str:
    parts = [f"<p>{html.escape(heading)}</p>"]
    line_items = "".join(f"<li>{html.escape(line)}</li>" for line in lines if line)
    if line_items:
        parts.append(f"<ul>{line_items}</ul>")
    field_items = "".join(
        f"<li><strong>{html.escape(key)}</strong>: {html.escape(str(value))}</li>"
        for key, value in fields.items()
    )
    if field_items:
        parts.append(f"<ul>{field_items}</ul>")
    return "".join(parts)


def _open_request(
    req: urllib.request.Request,
    *,
    verify_tls: bool,
    timeout: float,
) -> None:
    context = None
    if not verify_tls:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, context=context, timeout=timeout) as response:  # noqa: S310
        response.read()


def _send_slack(config: TeamsConfig, message: str, fields: Mapping[str, str]) -> None:
    if not config.url:
        raise TeamsNotificationError("SUGARKUBE_TEAMS_URL is required for Slack notifications")
    payload: Dict[str, object] = {"text": message}
    if config.username:
        payload["username"] = config.username
    if config.icon:
        payload["icon_emoji"] = config.icon
    if fields:
        attachments = [
            {
                "color": "#439FE0",
                "fields": [
                    {"title": key, "value": str(value), "short": False}
                    for key, value in fields.items()
                ],
            }
        ]
        payload["attachments"] = attachments
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        config.url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        _open_request(req, verify_tls=config.verify_tls, timeout=config.timeout)
    except urllib.error.URLError as exc:
        raise TeamsNotificationError(f"Slack webhook failed: {exc}") from exc


def _send_matrix(
    config: TeamsConfig,
    heading: str,
    lines: Sequence[str],
    fields: Mapping[str, str],
) -> None:
    if not config.url or not config.matrix_room or not config.auth_credential:
        raise TeamsNotificationError(
            "Matrix notifications require SUGARKUBE_TEAMS_URL, "
            "SUGARKUBE_TEAMS_MATRIX_ROOM, and SUGARKUBE_TEAMS_TOKEN"
        )
    room = urllib.parse.quote(config.matrix_room)
    txn_id = f"sugarkube-{int(time.time() * 1000)}-{random.randint(0, 9999)}"
    endpoint = (
        f"{config.url.rstrip('/')}/_matrix/client/v3/rooms/{room}/send/" f"m.room.message/{txn_id}"
    )
    html_body = _build_html(heading, lines, fields)
    message = _build_plaintext(heading, lines)
    payload = {
        "msgtype": "m.notice",
        "body": message,
        "format": "org.matrix.custom.html",
        "formatted_body": html_body,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        method="PUT",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.auth_credential}",
        },
    )
    try:
        _open_request(req, verify_tls=config.verify_tls, timeout=config.timeout)
    except urllib.error.URLError as exc:
        raise TeamsNotificationError(f"Matrix webhook failed: {exc}") from exc


class TeamsNotifier:
    """Send sugarkube automation updates to team chat systems."""

    def __init__(self, config: TeamsConfig):
        self.config = config

    @classmethod
    def from_env(cls) -> "TeamsNotifier":
        config = load_config()
        return cls(config)

    @property
    def enabled(self) -> bool:
        return self.config.enable and bool(self.config.url)

    def notify(
        self,
        *,
        event: str,
        status: str,
        lines: Sequence[str] | None = None,
        fields: Mapping[str, str] | None = None,
    ) -> None:
        if not self.enabled:
            return
        lines = lines or []
        fields = fields or {}
        heading = _format_heading(event, status)
        if self.config.kind == "matrix":
            _send_matrix(self.config, heading, lines, fields)
        else:
            message = _build_plaintext(heading, lines)
            _send_slack(self.config, message, fields)


def _parse_fields(values: Sequence[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise TeamsNotificationError("--field expects key=value entries")
        key, val = value.split("=", 1)
        parsed[key.strip()] = val.strip()
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send sugarkube webhook updates")
    parser.add_argument(
        "--event",
        choices=sorted(set(EVENT_LABELS) | {"custom"}),
        required=True,
        help="Event type to report",
    )
    parser.add_argument(
        "--status",
        choices=sorted(STATUS_EMOJIS),
        required=True,
        help="Notification status",
    )
    parser.add_argument(
        "--line",
        action="append",
        dest="lines",
        default=[],
        help="Additional message lines",
    )
    parser.add_argument(
        "--field",
        action="append",
        dest="fields",
        default=[],
        help="Key=value pairs included as structured fields",
    )
    args = parser.parse_args(argv)

    notifier = TeamsNotifier.from_env()
    try:
        notifier.notify(
            event=args.event,
            status=args.status,
            lines=args.lines,
            fields=_parse_fields(args.fields),
        )
    except TeamsNotificationError as exc:
        sys.stderr.write(f"sugarkube-teams error: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
