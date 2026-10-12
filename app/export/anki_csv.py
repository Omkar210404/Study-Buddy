"""Export a deck as a CSV file that Anki's text importer reads (File > Import).

Three columns: Front, Back, Tags. The lines starting with "#" are Anki file headers; they tell
the importer the separator, that fields contain HTML, and which column holds the tags.
The Back field is the answer followed by the supporting quote, so the source travels with the card.
Review history and scheduling are not exported: Anki's text import has no place for them.
"""

import csv
import io
import re
from dataclasses import dataclass
from html import escape

from app.text import strip_markers


@dataclass(frozen=True)
class ExportCard:
    front: str
    back: str
    quote: str
    tags: tuple[str, ...] = ()


def _field(text: str) -> str:
    """HTML-escape the text and keep its line breaks."""
    return escape(text.strip(), quote=False).replace("\r\n", "\n").replace("\n", "<br>")


def anki_tag(tag: str) -> str:
    """Anki separates tags with spaces, so a tag cannot contain one."""
    return re.sub(r"\s+", "_", tag.strip())


def deck_to_anki_csv(deck_name: str, cards: list[ExportCard]) -> str:
    buffer = io.StringIO()
    buffer.write("#separator:Comma\n")
    buffer.write("#html:true\n")
    buffer.write("#notetype:Basic\n")
    buffer.write(f"#deck:{' '.join(deck_name.split())}\n")
    buffer.write("#columns:Front,Back,Tags\n")
    buffer.write("#tags column:3\n")
    writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_ALL)
    for card in cards:
        quote = " ".join(strip_markers(card.quote).split())
        back = f"{_field(card.back)}<br><br><i>From your notes:</i> &ldquo;{_field(quote)}&rdquo;"
        tags = " ".join(sorted({anki_tag(tag) for tag in card.tags if tag.strip()}))
        writer.writerow([_field(card.front), back, tags])
    return buffer.getvalue()
