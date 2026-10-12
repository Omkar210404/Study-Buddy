"""Test helpers: build small PDFs in memory so no binary fixtures are committed."""

import io

from pypdf import PdfWriter


def make_text_pdf(pages: list[list[str]]) -> bytes:
    """A minimal text-based PDF: one list of lines per page, Helvetica 12pt."""
    objects: dict[int, bytes] = {}
    page_numbers = [4 + 2 * index for index in range(len(pages))]
    kids = " ".join(f"{number} 0 R" for number in page_numbers)
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for number, lines in zip(page_numbers, pages):
        ops = ["BT", "/F1 12 Tf", "72 720 Td"]
        for index, line in enumerate(lines):
            if index:
                ops.append("0 -16 Td")
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops.append(f"({escaped}) Tj")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        objects[number] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {number + 1} 0 R >>"
        ).encode()
        objects[number + 1] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += b"%d 0 obj\n" % number + objects[number] + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for number in sorted(objects):
        out += b"%010d 00000 n \n" % offsets[number]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref_at)
    return bytes(out)


def make_blank_pdf(pages: int = 1) -> bytes:
    """A PDF whose pages have no text at all, like a scan without OCR."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
