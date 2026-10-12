"""Small text helpers shared by ingestion, card generation and the mock provider."""

import re

_BULLET_RE = re.compile(r"^\s*(?:[-*+•]|\d{1,2}[.)])\s+")
_HEADING_LINE_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")
_SENTENCE_END_RE = re.compile(r"[.!?]+[\"')\]*`]*(?=\s|$)")
_TRAILING_TOKEN_RE = re.compile(r"([A-Za-z.]+)$")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-'/][A-Za-z0-9]+)*|\d+(?:[.,]\d+)*")

_ABBREVIATIONS = {"e.g", "i.e", "etc", "vs", "dr", "mr", "mrs", "ms", "prof", "fig", "no", "approx", "st", "cf"}

STOPWORDS = frozenset("""
a about above after again against all also although always am an and any are as at be because been
before being below between both but by can cannot could did do does doing down during each either
every few for from further had has have having he her here hers him his how however i if in into is
it its itself just like many may might more most much must my no nor not of off often on once one
only or other our out over own same she should since so some such than that the their them then
there these they this those through to too under until up upon us use used uses using very was we
were what when where whether which while who whom why will with within without would you your
called known means refers example examples e g i.e etc thing things way ways make makes made
inside outside across along around behind beyond toward towards among per via versus onto near
another several usually normally often sometimes still even long large larger small smaller high
higher low lower new old same different first last next right left part parts kind kinds type
types given gives give take takes need needs want wants let lets put puts get gets set sets
well back away together instead rather quite almost already later earlier above below
""".split())


def strip_markers(text: str) -> str:
    """Remove Markdown bold markers and backticks. Used for display and matching, never for stored quotes."""
    return text.replace("**", "").replace("`", "")


def collapse_ws(text: str) -> str:
    return " ".join(text.split())


def is_bullet(line: str) -> bool:
    return bool(_BULLET_RE.match(line))


def strip_bullet(text: str) -> str:
    return _BULLET_RE.sub("", text, count=1)


def words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def _units(text: str) -> list[tuple[int, int]]:
    """Spans of text that cannot share a sentence: paragraphs, list items and headings."""
    units: list[tuple[int, int]] = []
    start: int | None = None
    end = 0
    pos = 0
    for line in text.split("\n"):
        line_start, line_end = pos, pos + len(line)
        pos = line_end + 1
        if not line.strip():
            if start is not None:
                units.append((start, end))
                start = None
            continue
        if start is not None and (is_bullet(line) or _HEADING_LINE_RE.match(line)):
            units.append((start, end))
            start = None
        if start is None:
            start = line_start
        end = line_end
    if start is not None:
        units.append((start, end))
    return units


def _is_boundary(text: str, match: re.Match, unit_end: int) -> bool:
    before = _TRAILING_TOKEN_RE.search(text[max(0, match.start() - 20): match.start()])
    token = before.group(1).lower().strip(".") if before else ""
    if match.group(0).startswith(".") and before:
        if before.group(1).lower() in _ABBREVIATIONS or token in _ABBREVIATIONS or len(token) == 1:
            return False
    rest = text[match.end():unit_end].lstrip()
    if not rest:
        return True
    return rest[0].isupper() or rest[0].isdigit() or rest[0] in "\"'(*`["


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) offsets of each sentence. `text[start:end]` is the sentence, verbatim."""
    spans: list[tuple[int, int]] = []
    for unit_start, unit_end in _units(text):
        cursor = unit_start
        for match in _SENTENCE_END_RE.finditer(text, unit_start, unit_end):
            if _is_boundary(text, match, unit_end):
                spans.append((cursor, match.end()))
                cursor = match.end()
        if cursor < unit_end:
            spans.append((cursor, unit_end))
    trimmed: list[tuple[int, int]] = []
    for start, end in spans:
        chunk = text[start:end]
        lead = len(chunk) - len(chunk.lstrip())
        tail = len(chunk) - len(chunk.rstrip())
        if start + lead < end - tail:
            trimmed.append((start + lead, end - tail))
    return trimmed
