from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

MODULE_PATH = pathlib.Path("scripts/render_field_guide_pdf.py")
spec = importlib.util.spec_from_file_location("render_field_guide_pdf", MODULE_PATH)
assert spec and spec.loader
render_field_guide_pdf = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = render_field_guide_pdf
spec.loader.exec_module(render_field_guide_pdf)


def test_markdown_to_lines_formats_headings_lists():
    markdown = "\n".join(
        [
            "# Title",
            "",
            "## Tasks",
            "- First bullet with a [link](https://example.com).",
            "- Second bullet.",
            "1. Ordered step with `code`.",
            "",
            "Plain paragraph after lists.",
        ]
    )
    lines = render_field_guide_pdf.markdown_to_lines(markdown, wrap=60)
    assert lines[0] == "TITLE"
    assert lines[1] == "====="
    assert any("• First bullet" in line for line in lines)
    assert any("https://example.com" in line for line in lines)
    assert any(line.startswith(" 1.") for line in lines)
    assert any("code" in line for line in lines)


def test_lines_to_pdf_bytes_produces_pdf():
    layout = render_field_guide_pdf.Layout(height=200, margin=20, font_size=9, leading=11)
    lines = ["Header", "", "Line with (parentheses) and \\ slashes."]
    pdf = render_field_guide_pdf.lines_to_pdf_bytes(lines, layout=layout)
    assert pdf.startswith(b"%PDF-1.4")
    assert b"Header" in pdf
    assert b"parentheses" in pdf


def test_lines_to_pdf_bytes_overflow():
    layout = render_field_guide_pdf.Layout(height=100, margin=10, leading=10)
    lines = ["x"] * (layout.max_lines + 1)
    with pytest.raises(ValueError):
        render_field_guide_pdf.lines_to_pdf_bytes(lines, layout=layout)


def test_render_field_guide_pdf_round_trip(tmp_path: pathlib.Path):
    markdown = """# Heading\n\nParagraph with content."""
    source = tmp_path / "guide.md"
    output = tmp_path / "guide.pdf"
    source.write_text(markdown, encoding="utf-8")
    render_field_guide_pdf.render_field_guide_pdf(source, output, wrap=40)
    data = output.read_bytes()
    assert data.startswith(b"%PDF-1.4")
    assert b"HEADING" in data


def test_parse_args_overrides_paths(tmp_path: pathlib.Path):
    src = tmp_path / "a.md"
    dst = tmp_path / "b.pdf"
    args = render_field_guide_pdf.parse_args(
        [
            "--source",
            str(src),
            "--output",
            str(dst),
            "--wrap",
            "42",
        ]
    )
    assert args.source == src
    assert args.output == dst
    assert args.wrap == 42


def test_markdown_to_lines_spacing_and_empty_bullets():
    markdown = "\n".join(
        [
            "Paragraph without trailing blank before heading.",
            "# Following heading",
            "- ",
            "- Bullet with relative [link](docs/guide.md) that should wrap onto multiple "
            "continuation lines for coverage.",
            "",
        ]
    )

    lines = render_field_guide_pdf.markdown_to_lines(markdown, wrap=50)

    heading_index = lines.index("FOLLOWING HEADING")
    assert heading_index > 0
    assert lines[heading_index - 1] == ""

    assert any(line.startswith("  •") for line in lines)
    assert any("docs/guide.md" in line for line in lines)
    wrapped_continuations = [line for line in lines if line.startswith("    ")]
    assert wrapped_continuations, "expected continuation lines for wrapped bullets"
    assert lines[-1] != ""
