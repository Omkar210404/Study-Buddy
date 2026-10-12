"""Text normalisation for the grounding check.

Two strings are compared after the same small set of changes, none of which touches a word:
- Unicode compatibility forms are folded (NFKC), so a ligature or a non-breaking space matches
- curly quotes become straight quotes, and the various dashes become "-"
- every run of whitespace (spaces, tabs, line breaks) becomes one space
- Markdown bold markers (**) and backticks are ignored
Letter case is kept. Nothing fuzzy happens here.

The index map lets a match in the normalised text be turned back into offsets in the original.
"""

import unicodedata

_CHAR_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
}
_DROPPED = {"`", "​", "­", "﻿"}


def normalise_with_map(text: str) -> tuple[str, list[int]]:
    """Return the normalised text and, for each of its characters, the index it came from."""
    out: list[str] = []
    index_map: list[int] = []
    space_at: int | None = None
    for index, char in enumerate(text):
        if char == "*" and "*" in (text[index - 1:index], text[index + 1:index + 2]):
            continue
        for piece in unicodedata.normalize("NFKC", char):
            piece = _CHAR_MAP.get(piece, piece)
            if piece in _DROPPED:
                continue
            if piece.isspace():
                if space_at is None:
                    space_at = index
                continue
            if space_at is not None and out:
                out.append(" ")
                index_map.append(space_at)
            space_at = None
            out.append(piece)
            index_map.append(index)
    return "".join(out), index_map


def normalise(text: str) -> str:
    return normalise_with_map(text)[0]
