"""Turn pasted text or an uploaded file into one clean string.

That string is the canonical source text: it is what gets stored, and every passage offset
points into it. PDFs are read with pypdf, which extracts text that is already in the file.
Scanned PDFs are images of pages and have no such text; they are refused, not OCR'd.
"""

import io
import re
from dataclasses import dataclass
from pathlib import PurePath

from pypdf import PdfReader

from app.errors import IngestionError
from app.text import is_bullet

TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
MAX_PDF_PAGES = 200
# Below this many letters and digits per page on average, the PDF is treated as scanned.
MIN_CHARS_PER_PAGE = 25

SCANNED_PDF_MESSAGE = (
    "This looks like a scanned PDF: it has no text that can be read. "
    "Study Buddy reads text-based PDFs only and does not do OCR."
)


@dataclass(frozen=True)
class ExtractedText:
    text: str
    kind: str  # paste | txt | md | pdf
    # PDF only: offset in `text` where each page starts.
    page_starts: tuple[int, ...] = ()


def clean_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n").replace("﻿", "").replace("\x00", "")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def from_pasted(text: str) -> ExtractedText:
    cleaned = clean_text(text)
    if not cleaned:
        raise IngestionError("The notes are empty. Paste some text or choose a file.")
    return ExtractedText(text=cleaned, kind="paste")


def from_file(filename: str, data: bytes, max_bytes: int) -> ExtractedText:
    suffix = PurePath(filename).suffix.lower()
    if len(data) > max_bytes:
        raise IngestionError(f"The file is larger than the {max_bytes // (1024 * 1024)} MB limit.")
    if suffix in TEXT_SUFFIXES:
        return _from_text_file(data, "txt" if suffix == ".txt" else "md")
    if suffix == ".pdf":
        return _from_pdf(data)
    raise IngestionError(
        f"'{suffix or filename}' files are not supported. Use .txt, .md or a text-based PDF."
    )


def _from_text_file(data: bytes, kind: str) -> ExtractedText:
    if b"\x00" in data:
        raise IngestionError("This does not look like a text file.")
    try:
        raw = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raw = data.decode("cp1252", errors="replace")
    cleaned = clean_text(raw)
    if not cleaned:
        raise IngestionError("The file is empty.")
    return ExtractedText(text=cleaned, kind=kind)


def _from_pdf(data: bytes) -> ExtractedText:
    try:
        reader = PdfReader(io.BytesIO(data))
        encrypted = reader.is_encrypted
        page_count = len(reader.pages)
    except Exception as exc:  # pypdf raises several unrelated types for broken files
        raise IngestionError("The file could not be read as a PDF.") from exc
    if encrypted:
        raise IngestionError("This PDF is password-protected. Remove the password and try again.")
    if page_count == 0:
        raise IngestionError("The PDF has no pages.")
    if page_count > MAX_PDF_PAGES:
        raise IngestionError(f"The PDF has {page_count} pages; the limit is {MAX_PDF_PAGES}.")

    pages: list[str] = []
    for page in reader.pages:
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        pages.append(unwrap_pdf_page(raw))

    readable = sum(ch.isalnum() for text in pages for ch in text)
    if readable < MIN_CHARS_PER_PAGE * page_count:
        raise IngestionError(SCANNED_PDF_MESSAGE)

    parts: list[str] = []
    page_starts: list[int] = []
    offset = 0
    for text in pages:
        page_starts.append(offset)
        if text:
            parts.append(text)
            offset += len(text) + 2  # the "\n\n" that joins pages
    return ExtractedText(text="\n\n".join(parts), kind="pdf", page_starts=tuple(page_starts))


def unwrap_pdf_page(raw: str) -> str:
    """Rebuild paragraphs from a page of hard-wrapped lines.

    A line clearly shorter than the page's widest line is taken as the end of a paragraph
    (or a heading). A word split with a hyphen at a line break is joined again.
    """
    lines = [line.strip() for line in clean_text(raw).split("\n")]
    width = max((len(line) for line in lines), default=0)
    paragraphs: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            paragraphs.append(" ".join(current))
            current.clear()

    for line in lines:
        if not line:
            flush()
            continue
        if is_bullet(line):
            flush()
        if current and current[-1].endswith("-") and line[:1].islower():
            current[-1] = current[-1][:-1] + line
        else:
            current.append(line)
        if len(line) < 0.7 * width:
            flush()
    flush()
    return "\n\n".join(paragraphs)
