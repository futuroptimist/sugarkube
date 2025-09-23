#!/usr/bin/env python3
"""Render the Pi carrier field guide Markdown into a single-page PDF.

The generator intentionally avoids heavyweight dependencies so it can run in
automation without extra apt or pip installs. It supports a constrained subset
of Markdown that matches ``docs/pi_carrier_field_guide.md`` and exposes a small
CLI wrapper so ``make``/``just`` targets can refresh the PDF before releases.
"""
from __future__ import annotations

import argparse
import math
import pathlib
import re
import textwrap
from dataclasses import dataclass
from typing import Iterable, List

PDF_HEADER = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
PAGE_WIDTH = 612  # 8.5" * 72 pt
PAGE_HEIGHT = 792  # 11" * 72 pt
DEFAULT_MARGIN = 36
DEFAULT_FONT_SIZE = 10
LINE_SPACING = 11  # pts between lines
DEFAULT_WRAP = 74


@dataclass(frozen=True)
class Layout:
    """Layout controls for the single-page PDF."""

    width: int = PAGE_WIDTH
    height: int = PAGE_HEIGHT
    margin: int = DEFAULT_MARGIN
    font_size: int = DEFAULT_FONT_SIZE
    leading: int = LINE_SPACING

    @property
    def usable_height(self) -> int:
        return self.height - 2 * self.margin

    @property
    def max_lines(self) -> int:
        return max(0, math.floor(self.usable_height / self.leading))

    @property
    def baseline_y(self) -> int:
        return self.height - self.margin - self.font_size


_HEADING_UNDERLINES = {1: "=", 2: "-"}

_INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_CODE_RE = re.compile(r"`([^`]+)`")
_STRONG_RE = re.compile(r"\*\*([^*]+)\*\*")
_EM_RE = re.compile(r"\*([^*]+)\*")
_ORDERED_RE = re.compile(r"^(\d+)\.\s+(.*)$")


def _strip_markdown_markup(text: str) -> str:
    """Convert simple inline Markdown to printable text."""

    def _link_sub(match: re.Match[str]) -> str:
        label, url = match.group(1).strip(), match.group(2).strip()
        if url.startswith("http"):
            return f"{label} ({url})"
        return f"{label} ({url})"

    text = _INLINE_LINK_RE.sub(_link_sub, text)
    text = _CODE_RE.sub(lambda m: m.group(1), text)
    text = _STRONG_RE.sub(lambda m: m.group(1), text)
    text = _EM_RE.sub(lambda m: m.group(1), text)
    return text


def markdown_to_lines(markdown: str, wrap: int = DEFAULT_WRAP) -> List[str]:
    """Convert constrained Markdown into wrapped plaintext lines."""

    lines: List[str] = []
    previous_blank = True

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if not previous_blank:
                lines.append("")
            previous_blank = True
            continue

        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            heading_text = stripped[level:].strip()
            heading_text = _strip_markdown_markup(heading_text).upper()
            underline_char = _HEADING_UNDERLINES.get(level, "-")
            underline = underline_char * min(len(heading_text), wrap)
            if not previous_blank and lines and lines[-1] != "":
                lines.append("")
            lines.append(heading_text)
            lines.append(underline)
            lines.append("")
            previous_blank = True
            continue

        bullet_prefix = None
        if stripped.startswith("- "):
            bullet_prefix = "  • "
            body = stripped[2:].strip()
        else:
            ordered_match = _ORDERED_RE.match(stripped)
            if ordered_match:
                bullet_prefix = f" {ordered_match.group(1)}. "
                body = ordered_match.group(2).strip()

        if bullet_prefix is not None:
            body_text = _strip_markdown_markup(body)
            wrapped = textwrap.wrap(body_text, width=max(8, wrap - len(bullet_prefix)))
            if not wrapped:
                lines.append(bullet_prefix.rstrip())
            else:
                lines.append(bullet_prefix + wrapped[0])
                for cont in wrapped[1:]:
                    lines.append(" " * len(bullet_prefix) + cont)
            previous_blank = False
            continue

        paragraph_text = _strip_markdown_markup(stripped)
        wrapped = textwrap.wrap(paragraph_text, width=wrap)
        if not wrapped:
            wrapped = [""]
        lines.extend(wrapped)
        previous_blank = False

    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def lines_to_pdf_bytes(lines: Iterable[str], layout: Layout = Layout()) -> bytes:
    """Render wrapped lines into a single-page PDF and return the bytes."""

    lines_list = list(lines)
    if len(lines_list) > layout.max_lines:
        raise ValueError(
            "Field guide contains "
            f"{len(lines_list)} lines but only {layout.max_lines} fit on one page"
        )

    text_commands = [
        "BT",
        f"/F1 {layout.font_size} Tf",
        f"{layout.leading} TL",
        f"1 0 0 1 {layout.margin} {layout.baseline_y} Tm",
    ]

    for index, line in enumerate(lines_list):
        escaped = _escape_pdf_text(line)
        text_commands.append(f"({escaped}) Tj")
        if index != len(lines_list) - 1:
            text_commands.append("T*")

    text_commands.append("ET")
    text_stream = "\n".join(text_commands) + "\n"
    text_bytes = text_stream.encode("utf-8")

    objects: List[bytes] = []
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    objects.append(
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 /MediaBox [0 0 "
        + str(layout.width).encode("ascii")
        + b" "
        + str(layout.height).encode("ascii")
        + b"] >>\nendobj\n"
    )
    objects.append(
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/Contents 5 0 R >>\nendobj\n"
    )
    objects.append(b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")
    objects.append(
        b"5 0 obj\n<< /Length "
        + str(len(text_bytes)).encode("ascii")
        + b" >>\nstream\n"
        + text_bytes
        + b"endstream\nendobj\n"
    )

    pdf = bytearray()
    pdf.extend(PDF_HEADER)
    offsets = [0]  # object 0 is the free object at offset 0 per PDF spec

    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)

    startxref = len(pdf)
    obj_count = len(objects)
    pdf.extend(f"xref\n0 {obj_count + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010} 00000 n \n".encode("ascii"))

    pdf.extend(b"trailer\n<< /Size " + str(obj_count + 1).encode("ascii") + b" /Root 1 0 R >>\n")
    pdf.extend(b"startxref\n" + str(startxref).encode("ascii") + b"\n%%EOF\n")
    return bytes(pdf)


def render_field_guide_pdf(
    source: pathlib.Path, output: pathlib.Path, wrap: int = DEFAULT_WRAP
) -> None:
    markdown = source.read_text(encoding="utf-8")
    lines = markdown_to_lines(markdown, wrap=wrap)
    pdf_bytes = lines_to_pdf_bytes(lines)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(pdf_bytes)


def parse_args(args: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the Sugarkube field guide PDF")
    parser.add_argument(
        "--source",
        type=pathlib.Path,
        default=pathlib.Path("docs/pi_carrier_field_guide.md"),
        help="Path to the Markdown source document.",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("docs/pi_carrier_field_guide.pdf"),
        help="Destination PDF path.",
    )
    parser.add_argument(
        "--wrap",
        type=int,
        default=DEFAULT_WRAP,
        help="Column width used when wrapping Markdown paragraphs.",
    )
    return parser.parse_args(args=args)


def main(argv: Iterable[str] | None = None) -> None:
    opts = parse_args(argv)
    render_field_guide_pdf(opts.source, opts.output, wrap=opts.wrap)


if __name__ == "__main__":  # pragma: no cover - CLI shim
    main()
