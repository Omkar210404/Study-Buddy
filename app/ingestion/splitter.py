"""Split the canonical source text into passages.

A passage is one or more paragraphs under the same section title. Every passage keeps its
position: `text[start_char:end_char] == passage.text`, always.
"""

import re
from bisect import bisect_right
from dataclasses import dataclass

from app.text import collapse_ws, sentence_spans, strip_markers

MIN_CHARS = 200
MAX_CHARS = 1200

_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_UNDERLINE_RE = re.compile(r"^\s*(={3,}|-{3,})\s*$")
_NUMBERED_HEADING_RE = re.compile(r"^\d+(\.\d+)*\.?\s+[A-Z]")
_NOT_HEADING_START_RE = re.compile(r"^(?:[-*+>|`•]|\d{1,2}[.)]\s)")
_VERBS = {"is", "are", "was", "were", "has", "have", "had", "can", "will", "does", "do",
          "use", "uses", "means", "should", "must"}


@dataclass(frozen=True)
class Passage:
    ordinal: int
    section_title: str | None
    text: str
    start_char: int
    end_char: int
    page: int | None = None


@dataclass
class _Block:
    start: int
    end: int
    lines: int = 1
    heading: str | None = None  # set when the block is a section title, not body text


def _clean_title(raw: str) -> str:
    return collapse_ws(strip_markers(raw)).rstrip(":").strip()


def looks_like_heading(line: str) -> bool:
    """Conservative guess for plain-text notes that have no Markdown headings."""
    text = line.strip()
    if not text or len(text) > 60 or text[-1] in ".!?,;:":
        return False
    numbered = bool(_NUMBERED_HEADING_RE.match(text))
    if _NOT_HEADING_START_RE.match(text) and not numbered:
        return False
    tokens = text.split()
    if len(tokens) > 7:
        return False
    if numbered:
        return True
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) >= 3 and all(ch.isupper() for ch in letters):
        return True
    return (
        len(tokens) <= 5
        and text[0].isupper()
        and not any(token.lower() in _VERBS for token in tokens)
    )


def _blocks(text: str) -> list[_Block]:
    blocks: list[_Block] = []
    current: _Block | None = None
    pos = 0
    for line in text.split("\n"):
        start, end = pos, pos + len(line)
        pos = end + 1
        if not line.strip():
            current = None
            continue
        md = _MD_HEADING_RE.match(line)
        if md:
            blocks.append(_Block(start, end, heading=_clean_title(md.group(1))))
            current = None
            continue
        if _UNDERLINE_RE.match(line):
            # "Title" over "====" or "----" is a heading; a rule on its own is ignored.
            if current is not None and current.lines == 1:
                current.heading = _clean_title(text[current.start:current.end])
            current = None
            continue
        if current is None:
            current = _Block(start, end)
            blocks.append(current)
        else:
            current.end = end
            current.lines += 1

    for index, block in enumerate(blocks[:-1]):
        nxt = blocks[index + 1]
        if block.heading is None and block.lines == 1 and nxt.heading is None:
            line = text[block.start:block.end]
            if looks_like_heading(line):
                block.heading = _clean_title(line)
    return blocks


def _split_long(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    """Cut one over-long block at sentence boundaries; a single huge sentence is cut at a space."""
    pieces: list[tuple[int, int]] = []
    for s_start, s_end in sentence_spans(text[start:end]):
        s_start, s_end = s_start + start, s_end + start
        while s_end - s_start > max_chars:
            cut = text.rfind(" ", s_start, s_start + max_chars)
            cut = cut if cut > s_start else s_start + max_chars
            pieces.append((s_start, cut))
            s_start = cut + 1 if text[cut:cut + 1] == " " else cut
        if s_start < s_end:
            pieces.append((s_start, s_end))

    chunks: list[tuple[int, int]] = []
    for p_start, p_end in pieces:
        if chunks and p_end - chunks[-1][0] <= max_chars:
            chunks[-1] = (chunks[-1][0], p_end)
        else:
            chunks.append((p_start, p_end))
    return chunks


def split_passages(text: str, page_starts: tuple[int, ...] = (),
                   min_chars: int = MIN_CHARS, max_chars: int = MAX_CHARS) -> list[Passage]:
    spans: list[tuple[int, int, str | None]] = []
    section: str | None = None
    buffer: tuple[int, int] | None = None

    def flush() -> None:
        nonlocal buffer
        if buffer is None:
            return
        start, end = buffer
        buffer = None
        # A short leftover joins the passage before it when both are in the same section.
        if spans and end - start < min_chars:
            prev_start, _prev_end, prev_section = spans[-1]
            if prev_section == section and end - prev_start <= max_chars:
                spans[-1] = (prev_start, end, section)
                return
        spans.append((start, end, section))

    for block in _blocks(text):
        if block.heading is not None:
            flush()
            section = block.heading or None
            continue
        if block.end - block.start > max_chars:
            flush()
            for start, end in _split_long(text, block.start, block.end, max_chars):
                spans.append((start, end, section))
            continue
        if buffer is None:
            buffer = (block.start, block.end)
        elif buffer[1] - buffer[0] < min_chars and block.end - buffer[0] <= max_chars:
            buffer = (buffer[0], block.end)
        else:
            flush()
            buffer = (block.start, block.end)
    flush()

    passages: list[Passage] = []
    for ordinal, (start, end, title) in enumerate(spans):
        page = bisect_right(page_starts, start) if page_starts else None
        passages.append(Passage(ordinal, title, text[start:end], start, end, page))
    return passages
