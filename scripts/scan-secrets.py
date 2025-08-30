#!/usr/bin/env python3
"""Scan text from stdin for common secret patterns.

Exits with status 1 if potential secrets are found, otherwise 0.
"""
import re
import sys

PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key ID"),
    (
        re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*[0-9a-zA-Z/+]{40}"),
        "AWS Secret Access Key",
    ),
    (re.compile(r"-----BEGIN[ \w]*PRIVATE KEY-----"), "Private key"),
    (re.compile(r"(?i)password\s*[:=]\s*[^\s]+"), "Password assignment"),
]


def _mask(value: str) -> str:
    """Mask the middle of a string to avoid leaking secrets."""
    if len(value) <= 8:
        return value
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def main() -> int:
    data = sys.stdin.read()
    findings = []
    for pattern, label in PATTERNS:
        for match in pattern.finditer(data):
            findings.append((label, _mask(match.group(0))))

    if findings:
        print("Potential secrets detected:")
        for label, value in findings:
            print(f" - {label}: {value}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
