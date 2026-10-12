"""The grounding validator. Pure functions: no database, no network, no model.

`check_quote` answers one question: does this quote really appear in this passage?
It proves the quote exists in the notes. It does not prove that a card's answer follows
from the quote; that is why the quote is shown on the back of every card.
"""

from pydantic import BaseModel

from app.grounding.normalise import normalise, normalise_with_map

MIN_QUOTE_CHARS = 12
MIN_QUOTE_WORDS = 3
MAX_QUOTE_CHARS = 300

# Every reason a proposed card can be turned down, with the sentence shown to the learner.
REASONS = {
    "quote_missing": "The card came without a supporting quote.",
    "quote_too_short": f"The quote is too short to support anything (under {MIN_QUOTE_WORDS} words "
                       f"or {MIN_QUOTE_CHARS} characters).",
    "quote_too_long": f"The quote is longer than {MAX_QUOTE_CHARS} characters; a quote should point "
                      "at one place in the notes.",
    "quote_not_found": "The quote does not appear in the passage it claims to come from.",
    "duplicate": "A card with the same question already exists in this deck.",
    "invalid_schema": "The card was missing a question, an answer or a quote.",
    "invalid_json": "The model's reply for this passage was not valid JSON.",
    "provider_error": "The provider failed for this passage.",
}

_WRAPPERS = "\"'"


class GroundingResult(BaseModel):
    ok: bool
    reason: str | None = None
    # The exact text from the passage (not the wording that was submitted) and where it sits.
    quote: str | None = None
    start: int | None = None
    end: int | None = None

    @property
    def message(self) -> str | None:
        return REASONS.get(self.reason) if self.reason else None


def _rejected(reason: str) -> GroundingResult:
    return GroundingResult(ok=False, reason=reason)


def _balance_markers(passage: str, start: int, end: int) -> tuple[int, int]:
    """Markdown markers are ignored when matching, so widen the span to keep `**` and ` in pairs."""
    for marker in ("**", "`"):
        if passage.count(marker, start, end) % 2 == 0:
            continue
        if passage[max(0, start - len(marker)):start] == marker:
            start -= len(marker)
        elif passage[end:end + len(marker)] == marker:
            end += len(marker)
    return start, end


def check_quote(quote: str | None, passage: str) -> GroundingResult:
    """Accept the quote only if, after normalisation, it is a substring of the passage."""
    wanted = normalise(quote or "")
    if not wanted:
        return _rejected("quote_missing")
    haystack, index_map = normalise_with_map(passage)

    at = haystack.find(wanted)
    if at == -1 and len(wanted) > 2 and wanted[0] in _WRAPPERS and wanted[-1] == wanted[0]:
        # Models often wrap the quote in quotation marks of their own.
        unwrapped = wanted[1:-1].strip()
        if unwrapped and haystack.find(unwrapped) != -1:
            wanted, at = unwrapped, haystack.find(unwrapped)

    if len(wanted) < MIN_QUOTE_CHARS or len(wanted.split()) < MIN_QUOTE_WORDS:
        return _rejected("quote_too_short")
    if len(wanted) > MAX_QUOTE_CHARS:
        return _rejected("quote_too_long")
    if at == -1:
        return _rejected("quote_not_found")

    start = index_map[at]
    end = index_map[at + len(wanted) - 1] + 1
    start, end = _balance_markers(passage, start, end)
    return GroundingResult(ok=True, quote=passage[start:end], start=start, end=end)


def question_key(question: str) -> str:
    """Two questions with the same key count as duplicates."""
    return normalise(question).casefold().rstrip("?.! ")
