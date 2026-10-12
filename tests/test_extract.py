import pytest

from app.errors import IngestionError
from app.ingestion.extract import clean_text, from_file, from_pasted, unwrap_pdf_page
from app.ingestion.splitter import split_passages
from tests.helpers import make_blank_pdf, make_text_pdf

MB = 1024 * 1024


def test_pasted_text_is_cleaned():
    extracted = from_pasted("﻿Line one  \r\nLine two\r\n\r\n\r\n\r\nLine three\n")
    assert extracted.kind == "paste"
    assert extracted.text == "Line one\nLine two\n\nLine three"


def test_empty_paste_is_refused():
    with pytest.raises(IngestionError, match="empty"):
        from_pasted("  \n\n ")


def test_txt_and_md_files_are_decoded():
    assert from_file("notes.txt", "Café notes".encode("utf-8"), MB).kind == "txt"
    assert from_file("notes.MD", b"# Title\n\nBody", MB).kind == "md"
    assert from_file("notes.txt", "Café notes".encode("utf-8"), MB).text == "Café notes"


def test_non_utf8_text_falls_back_to_cp1252():
    assert from_file("notes.txt", "Café".encode("cp1252"), MB).text == "Café"


def test_unsupported_type_and_oversize_are_refused():
    with pytest.raises(IngestionError, match="not supported"):
        from_file("notes.docx", b"anything", MB)
    with pytest.raises(IngestionError, match="larger than"):
        from_file("notes.txt", b"x" * (MB + 1), MB)
    with pytest.raises(IngestionError, match="text file"):
        from_file("notes.txt", b"abc\x00def", MB)


def test_text_pdf_is_extracted_with_page_positions():
    pdf = make_text_pdf([
        ["A router forwards packets between networks.", "It reads the destination address."],
        ["A switch connects devices inside one network.", "It reads the MAC address."],
    ])
    extracted = from_file("notes.pdf", pdf, MB)
    assert extracted.kind == "pdf"
    assert "A router forwards packets between networks." in extracted.text
    assert "A switch connects devices inside one network." in extracted.text
    assert len(extracted.page_starts) == 2
    second = extracted.text[extracted.page_starts[1]:]
    assert second.startswith("A switch connects")
    passages = split_passages(extracted.text, extracted.page_starts, min_chars=10)
    assert {p.page for p in passages} == {1, 2}


def test_pdf_without_text_is_refused_as_scanned():
    with pytest.raises(IngestionError, match="scanned PDF") as excinfo:
        from_file("scan.pdf", make_blank_pdf(2), MB)
    assert "OCR" in str(excinfo.value)


def test_broken_pdf_is_refused():
    with pytest.raises(IngestionError, match="could not be read"):
        from_file("broken.pdf", b"this is not a pdf", MB)


def test_unwrap_pdf_page_joins_wrapped_lines_and_hyphens():
    raw = (
        "Transport layer\n"
        "The transport layer moves data between appli-\n"
        "cations running on different hosts and it can\n"
        "add reliability.\n"
        "The network layer moves packets between hosts\n"
        "across many networks."
    )
    assert unwrap_pdf_page(raw) == (
        "Transport layer\n\n"
        "The transport layer moves data between applications running on different hosts and it can "
        "add reliability.\n\n"
        "The network layer moves packets between hosts across many networks."
    )


def test_clean_text_collapses_blank_runs():
    assert clean_text("a\n\n\n\n\nb") == "a\n\nb"
