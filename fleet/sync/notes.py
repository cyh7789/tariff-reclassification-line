"""Fetch the legal notes of every HTS chapter.

Chapter and section notes decide classifications that the tariff line descriptions
alone cannot: an exclusion note ("this chapter does not cover ...") settles a
candidate faster than any positive argument about what the goods are. They are not
in the JSON export, only in the per-chapter PDF, so this source exists to pull
them out.

Endpoint, verified 2026-08-17 (chapter 85 returns 200 with a 1.17 MB PDF):

    https://hts.usitc.gov/reststop/file?release=currentRelease&filename=Chapter%20<n>

Extraction stops at the first tariff line, because everything past it is the
schedule itself, which the `hts` source already carries in a far more usable form.

External dependency: `pdftotext` from poppler, as with `correlation`. Its absence
raises rather than silently falling back to a different parse.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

from fleet.sync import cli, http
from fleet.sync.gate import DataSourceUnhealthy
from fleet.sync.manifest import Manifest, build_manifest, data_path, utc_now, write_manifest

SOURCE = "notes"
URL_TEMPLATE = "https://hts.usitc.gov/reststop/file?release=currentRelease&filename=Chapter%20{n}"
URL = URL_TEMPLATE.format(n="<n>")

# Chapter 77 is reserved for future use and has no file.
CHAPTERS = [n for n in range(1, 100) if n != 77]

MIN_ROWS = 90
MIN_BYTES = 200_000
MIN_PDF_BYTES = 10_000

# Notes run from the heading down to the first tariff line, which starts with a
# 4-digit heading followed by a dot, near the left margin.
# Real headings seen in 2026HTSRev16: "Notes", "Notes:", "U.S. Notes",
# "Additional U.S. Notes", "Statistical Note" (chapter 53 has only that one), and
# the singular forms. A variant this misses does not fail loudly; it just reports
# the chapter as having no notes, which reads to the agent as nothing to check.
NOTES_START = re.compile(
    r"^[ \t]*(?:Additional[ \t]+)?(?:U\.S\.[ \t]+)?"
    r"(?:Subheading[ \t]+|Statistical[ \t]+)?Notes?[ \t]*:?[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)
TARIFF_LINE = re.compile(r"^[ \t]{0,8}\d{4}\.\d{2}", re.MULTILINE)
# "SECTION XVI" on its own line, and the "CHAPTER 84" heading that ends the
# section's own notes.
SECTION_HEADING = re.compile(r"^[ \t]*SECTION[ \t]+([IVXL]+)[ \t]*$", re.MULTILINE)
CHAPTER_HEADING = r"^[ \t]*CHAPTER[ \t]+0*{n}[ \t]*$"
PAGE_FURNITURE = re.compile(
    r"^.*(?:Harmonized Tariff Schedule of the United States"
    r"|Annotated for Statistical Reporting Purposes).*$",
    re.MULTILINE,
)


def find_section(text: str) -> str | None:
    """The Roman numeral of the section this chapter file opens with, if any."""
    match = SECTION_HEADING.search(text)
    return match.group(1) if match else None


def split_notes(text: str, chapter: int) -> tuple[str, str]:
    """Return (section notes, chapter notes) from one chapter file.

    Only the first chapter of a section carries that section's notes, and it
    carries them ahead of its own. Both blocks answer different citations, so
    keeping them apart is what lets `Note 6 to Section XVI` resolve against the
    section rather than against whichever chapter happened to store it.
    """
    heading = re.search(CHAPTER_HEADING.format(n=chapter), text, re.MULTILINE)
    if not heading:
        return "", extract_notes(text)
    before, after = text[:heading.start()], text[heading.end():]
    return extract_notes(before), extract_notes(after)


def extract_notes(text: str) -> str:
    """Return the notes block of one chapter, or an empty string when it has none."""
    start = NOTES_START.search(text)
    if not start:
        return ""
    body = text[start.end():]
    end = TARIFF_LINE.search(body)
    if end:
        body = body[:end.start()]
    body = PAGE_FURNITURE.sub("", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def fetch(out_dir: Path, *, session: requests.Session | None = None) -> Manifest:
    if not shutil.which("pdftotext"):
        raise DataSourceUnhealthy(
            f"{SOURCE}: pdftotext (poppler) is required to read the chapter PDFs; "
            "install it rather than letting this source fall back to a weaker parse"
        )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = session or http.new_session()

    fetched_at = utc_now()
    path = data_path(out_dir, SOURCE)
    written = 0
    empty = []

    with tempfile.TemporaryDirectory() as tmp, path.open("w", encoding="utf-8") as fh:
        for chapter in CHAPTERS:
            url = URL_TEMPLATE.format(n=chapter)
            response = http.get(session, url, min_bytes=MIN_PDF_BYTES, source=SOURCE)
            pdf = Path(tmp) / f"ch{chapter:02d}.pdf"
            pdf.write_bytes(response.body)
            txt = pdf.with_suffix(".txt")
            subprocess.run(
                ["pdftotext", "-layout", str(pdf), str(txt)],
                check=True, capture_output=True,
            )
            page = txt.read_text(encoding="utf-8", errors="replace")
            section_notes, notes = split_notes(page, chapter)
            if not notes:
                empty.append(chapter)
            fh.write(json.dumps({
                "chapter": f"{chapter:02d}",
                "section": find_section(page),
                "notes": notes,
                "section_notes": section_notes,
                "chars": len(notes),
                "section_chars": len(section_notes),
                "url": url,
            }, ensure_ascii=False) + "\n")
            written += 1

    # A handful of chapters genuinely carry no notes, but a wholesale extraction
    # failure looks identical to that from the row count alone.
    if len(empty) > 15:
        raise DataSourceUnhealthy(
            f"{SOURCE}: {len(empty)} of {written} chapters extracted no notes "
            f"({empty[:10]}...); the layout parse has probably broken"
        )

    manifest = build_manifest(
        source=SOURCE,
        url=URL,
        snapshot_dir=out_dir,
        fetched_at=fetched_at,
        revision=None,
        row_count=written,
        min_rows=MIN_ROWS,
        min_bytes=MIN_BYTES,
        last_modified=None,
    )
    write_manifest(out_dir, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = cli.build_parser(__doc__.splitlines()[0]).parse_args(argv)
    cli.report(fetch(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
