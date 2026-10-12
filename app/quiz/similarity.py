"""Typed-answer check. A plain string comparison, not grading by a model.

1. Both strings are normalised: Unicode folded, lower-cased, punctuation turned into spaces,
   thousands separators removed, spaces collapsed, a leading "a", "an" or "the" dropped.
2. Equal after that: correct ("exact").
3. Otherwise Python's difflib.SequenceMatcher gives a ratio from 0 to 1 (twice the number of
   matching characters divided by the total length of both strings). A ratio of 0.85 or more
   counts as correct ("close"), which forgives a typo or a plural.
4. If the expected answer contains a digit, only an exact match counts: 192.168.1.21 is not a
   typo of 192.168.1.20.

The learner always sees both strings and the ratio, and can overrule the verdict.
"""

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

CLOSE_THRESHOLD = 0.85

_ARTICLE_RE = re.compile(r"^(?:a|an|the)\s+(?=\S)")
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}\b)")
_KEEP_IN_NUMBERS_RE = re.compile(r"(?<=\d)[.](?=\d)")
_DOT = chr(0xE000)  # private-use placeholder for a dot that must survive punctuation removal


def normalise_answer(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = _THOUSANDS_RE.sub("", text)
    text = _KEEP_IN_NUMBERS_RE.sub(_DOT, text)  # protect decimal points and dotted addresses
    text = "".join(ch if ch.isalnum() or ch == _DOT else " " for ch in text)
    text = " ".join(text.replace(_DOT, ".").split())
    return _ARTICLE_RE.sub("", text)


@dataclass(frozen=True)
class AnswerCheck:
    verdict: str  # exact | close | wrong
    similarity: float
    typed: str
    expected: str

    @property
    def correct(self) -> bool:
        return self.verdict != "wrong"


def check_answer(typed: str, expected: str) -> AnswerCheck:
    typed_norm, expected_norm = normalise_answer(typed), normalise_answer(expected)
    if not typed_norm:
        return AnswerCheck("wrong", 0.0, typed_norm, expected_norm)
    if typed_norm == expected_norm:
        return AnswerCheck("exact", 1.0, typed_norm, expected_norm)
    ratio = round(SequenceMatcher(None, typed_norm, expected_norm, autojunk=False).ratio(), 2)
    has_digit = any(ch.isdigit() for ch in expected_norm)
    verdict = "close" if ratio >= CLOSE_THRESHOLD and not has_digit else "wrong"
    return AnswerCheck(verdict, ratio, typed_norm, expected_norm)
