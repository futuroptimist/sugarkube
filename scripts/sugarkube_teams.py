#!/usr/bin/env python3
"""Send Sugarkube status notifications to Slack-style webhooks or Matrix rooms."""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

STATUS_EMOJI = {
    "started": "🟡",
    "success": "✅",
    "warning": "⚠️",
    "failure": "❌",
    "info": "ℹ️",
}

STATUS_LABELS = {
    "started": "Started",
    "success": "Success",
    "warning": "Warning",
    "failure": "Failure",
    "info": "Info",
}


class NotificationError(RuntimeError):
    """Raised when a notification cannot be delivered."""


@dataclass
class MatrixConfig:
    homeserver: str
    room: str
    auth_key: str
    timeout: float = 10.0


@dataclass
class Destinations:
    webhook_url: Optional[str]
    matrix: Optional[MatrixConfig]


def _ensure_status(value: str) -> str:
    if value not in STATUS_EMOJI:
        raise NotificationError(f"Unsupported status '{value}'.")
    return value


def _coerce_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not metadata:
        return {}
    clean: Dict[str, Any] = {}
    for key, value in metadata.items():
        if isinstance(value, (dict, list)):
            clean[key] = value
        elif value is None:
            continue
        else:
            clean[key] = value
    return clean


def _format_metadata_lines(metadata: Dict[str, Any]) -> Iterable[str]:
    for key in sorted(metadata):
        value = metadata[key]
        if isinstance(value, (dict, list)):
            value_str = json.dumps(value, sort_keys=True)
        else:
            value_str = str(value)
        yield f"- {key}: {value_str}"


def render_messages(
    event: str,
    status: str,
    summary: str,
    *,
    metadata: Optional[Dict[str, Any]] = None,
    details: Optional[str] = None,
    label: Optional[str] = None,
) -> tuple[str, str]:
    status = _ensure_status(status)
    prefix = STATUS_EMOJI.get(status, "ℹ️")
    parts = [event]
    if label:
        parts.insert(0, label)
    header = f"{prefix} {' · '.join(parts)}: {summary.strip()}"
    lines = [header]

    clean_metadata = _coerce_metadata(metadata)
    if clean_metadata:
        lines.extend(_format_metadata_lines(clean_metadata))

    if details:
        lines.append("")
        lines.append(details.strip())

    plain = "\n".join(lines)

    html_lines = [
        f"<p><strong>{html.escape(' · '.join(parts))}</strong>: {html.escape(summary.strip())} "
        f"<span>({html.escape(STATUS_LABELS.get(status, status).lower())})</span></p>",
    ]

    if clean_metadata:
        meta_items = [
            f"<li><code>{html.escape(str(key))}</code>: {html.escape(str(value))}</li>"
            for key, value in sorted(clean_metadata.items())
        ]
        html_lines.append("<ul>%s</ul>" % "".join(meta_items))

    if details:
        html_lines.append("<pre>%s</pre>" % html.escape(details.strip()))

    html_message = "".join(html_lines)
    return plain, html_message


def _post_json(url: str, payload: Dict[str, Any], *, timeout: float) -> None:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
    except urllib.error.URLError as exc:
        raise NotificationError(f"Failed to POST to {url}: {exc}") from exc


def send_webhook(url: str, message: str, *, timeout: float = 10.0) -> None:
    payload = {"text": message}
    _post_json(url, payload, timeout=timeout)


def send_matrix(config: MatrixConfig, plain: str, html_message: str) -> None:
    room = urllib.parse.quote(config.room, safe="")
    txn_id = uuid.uuid4().hex
    base = config.homeserver.rstrip("/")
    endpoint = f"{base}/_matrix/client/v3/rooms/{room}/send/"
    endpoint += f"m.room.message/{txn_id}"
    payload = {
        "msgtype": "m.notice",
        "body": plain,
        "format": "org.matrix.custom.html",
        "formatted_body": html_message,
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(endpoint, data=data, method="PUT")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Bearer {config.auth_key}")
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            response.read()
    except urllib.error.URLError as exc:
        raise NotificationError(f"Failed to send Matrix event: {exc}") from exc


def destinations_from_env(timeout: float = 10.0) -> Destinations:
    webhook = os.environ.get("SUGARKUBE_TEAMS_WEBHOOK_URL")
    homeserver = os.environ.get("SUGARKUBE_MATRIX_HOMESERVER")
    room = os.environ.get("SUGARKUBE_MATRIX_ROOM")
    auth_key = os.environ.get("SUGARKUBE_MATRIX_ACCESS_TOKEN")
    matrix_timeout = os.environ.get("SUGARKUBE_MATRIX_TIMEOUT")
    if matrix_timeout:
        try:
            timeout = float(matrix_timeout)
        except ValueError as exc:
            raise NotificationError("SUGARKUBE_MATRIX_TIMEOUT must be numeric") from exc
    matrix = None
    if homeserver and room and auth_key:
        matrix = MatrixConfig(
            homeserver=homeserver,
            room=room,
            auth_key=auth_key,
            timeout=timeout,
        )
    return Destinations(webhook_url=webhook, matrix=matrix)


def notify_event(
    event: str,
    status: str,
    summary: str,
    *,
    metadata: Optional[Dict[str, Any]] = None,
    details: Optional[str] = None,
    label: Optional[str] = None,
    destinations: Optional[Destinations] = None,
    timeout: float = 10.0,
    dry_run: bool = False,
) -> bool:
    if destinations is None:
        destinations = destinations_from_env(timeout)

    plain, html_message = render_messages(
        event,
        status,
        summary,
        metadata=metadata,
        details=details,
        label=label,
    )

    delivered = False
    if dry_run:
        print(plain)
        return True

    if destinations.webhook_url:
        send_webhook(destinations.webhook_url, plain, timeout=timeout)
        delivered = True

    if destinations.matrix:
        send_matrix(destinations.matrix, plain, html_message)
        delivered = True

    return delivered


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True, help="Event name, e.g. first-boot or ssd-clone")
    parser.add_argument(
        "--status",
        required=True,
        choices=sorted(STATUS_EMOJI.keys()),
        help="Event status",
    )
    parser.add_argument("--summary", required=True, help="Short human-readable summary")
    parser.add_argument("--details", help="Optional multi-line details")
    parser.add_argument("--metadata", help="JSON metadata to attach to the message")
    parser.add_argument("--label", default=os.environ.get("SUGARKUBE_TEAMS_LABEL"))
    parser.add_argument("--webhook-url", default=os.environ.get("SUGARKUBE_TEAMS_WEBHOOK_URL"))
    parser.add_argument(
        "--matrix-homeserver",
        default=os.environ.get("SUGARKUBE_MATRIX_HOMESERVER"),
    )
    parser.add_argument(
        "--matrix-room",
        default=os.environ.get("SUGARKUBE_MATRIX_ROOM"),
    )
    parser.add_argument(
        "--matrix-auth-key",
        dest="matrix_auth_key",
        default=os.environ.get("SUGARKUBE_MATRIX_ACCESS_TOKEN"),
        help="Matrix access token for posting events",
    )
    parser.add_argument(
        "--matrix-timeout",
        type=float,
        default=float(os.environ.get("SUGARKUBE_MATRIX_TIMEOUT", "10")),
        help="Matrix request timeout (seconds)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("SUGARKUBE_TEAMS_TIMEOUT", "10")),
        help="Webhook timeout (seconds)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print message without sending")
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    metadata = None
    if args.metadata:
        try:
            metadata = json.loads(args.metadata)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--metadata must be valid JSON: {exc}")

    destinations = Destinations(
        webhook_url=args.webhook_url,
        matrix=None,
    )
    if args.matrix_homeserver and args.matrix_room and args.matrix_auth_key:
        destinations.matrix = MatrixConfig(
            homeserver=args.matrix_homeserver,
            room=args.matrix_room,
            auth_key=args.matrix_auth_key,
            timeout=args.matrix_timeout,
        )

    if not destinations.webhook_url and not destinations.matrix and not args.dry_run:
        print("No destinations configured; nothing to do.", file=sys.stderr)
        return 0

    try:
        delivered = notify_event(
            args.event,
            args.status,
            args.summary,
            metadata=metadata,
            details=args.details,
            label=args.label,
            destinations=destinations,
            timeout=args.timeout,
            dry_run=args.dry_run,
        )
    except NotificationError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not delivered and not args.dry_run:
        print("No notification sent; verify configuration.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
