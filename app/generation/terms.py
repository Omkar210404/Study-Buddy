"""Key-term scoring for cloze cards. Counting and a few boosts; no model, no external data.

score = (1 + ln(term frequency)) * ln(1 + passages / passages containing the term) * boosts

Boosts: the notes marked the term in bold or code (x2.0), it appears in a heading (x1.4), it is
an acronym (x1.5), it is capitalised in the middle of sentences (x1.3), it is a two-word phrase
(x1.2). A plain word seen only once is damped (x0.6). Numbers get a fixed score.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

from app.text import STOPWORDS, WORD_RE, sentence_spans, strip_bullet, strip_markers

EMPHASIS_BOOST = 2.0
HEADING_BOOST = 1.4
ACRONYM_BOOST = 1.5
PROPER_BOOST = 1.3
PHRASE_BOOST = 1.2
SINGLE_USE_DAMPING = 0.6
NUMBER_SCORE = 2.0

_EMPHASIS_RE = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int

    @property
    def key(self) -> str:
        return self.text.lower()


def tokens(text: str) -> list[Token]:
    return [Token(m.group(0), m.start(), m.end()) for m in WORD_RE.finditer(text)]


def is_number(text: str) -> bool:
    return bool(_NUMBER_RE.fullmatch(text))


def is_acronym(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    return 2 <= len(letters) <= 6 and all(ch.isupper() for ch in letters)


def _is_candidate_word(token: Token) -> bool:
    if is_number(token.text) or token.key in STOPWORDS:
        return False
    return len(token.text) >= 4 or is_acronym(token.text)


def phrase_pairs(sentence_tokens: list[Token], text: str) -> list[tuple[Token, Token]]:
    """Adjacent candidate words separated by exactly one space."""
    pairs = []
    for first, second in zip(sentence_tokens, sentence_tokens[1:]):
        if text[first.end:second.start] == " " and _is_candidate_word(first) and _is_candidate_word(second):
            pairs.append((first, second))
    return pairs


def score_terms(passages: list[str], headings: list[str]) -> dict[str, float]:
    """Map each candidate term (lower case, one or two words) to its score."""
    tf: Counter[str] = Counter()
    df: Counter[str] = Counter()
    acronyms: set[str] = set()
    capitalised: Counter[str] = Counter()
    emphasised: set[str] = set()
    phrases: set[str] = set()

    for raw in passages:
        for match in _EMPHASIS_RE.finditer(raw):
            emphasised.add(" ".join((match.group(1) or match.group(2)).lower().split()))
        clean = strip_markers(raw)
        seen: set[str] = set()
        for start, end in sentence_spans(clean):
            sentence = strip_bullet(clean[start:end])
            sentence_tokens = tokens(sentence)
            for position, token in enumerate(sentence_tokens):
                if not _is_candidate_word(token):
                    continue
                tf[token.key] += 1
                seen.add(token.key)
                if is_acronym(token.text):
                    acronyms.add(token.key)
                elif position > 0 and token.text[0].isupper():
                    capitalised[token.key] += 1
            for first, second in phrase_pairs(sentence_tokens, sentence):
                key = f"{first.key} {second.key}"
                tf[key] += 1
                seen.add(key)
                phrases.add(key)
        df.update(seen)

    heading_terms: set[str] = set()
    for heading in headings:
        heading_tokens = [t for t in tokens(strip_markers(heading)) if _is_candidate_word(t)]
        heading_terms.update(t.key for t in heading_tokens)
        heading_terms.update(f"{a.key} {b.key}" for a, b in zip(heading_tokens, heading_tokens[1:]))

    total = max(len(passages), 1)
    scores: dict[str, float] = {}
    for term, count in tf.items():
        boosted = term in emphasised or term in heading_terms or term in acronyms
        if term in phrases and count < 2 and not boosted:
            continue  # a word pair seen once is usually a coincidence, not a term
        score = (1 + math.log(count)) * math.log(1 + total / df[term])
        if term in emphasised:
            score *= EMPHASIS_BOOST
        if term in heading_terms:
            score *= HEADING_BOOST
        if term in acronyms:
            score *= ACRONYM_BOOST
        elif capitalised[term] * 2 > count:
            score *= PROPER_BOOST
            boosted = True
        if term in phrases:
            score *= PHRASE_BOOST
        elif count == 1 and not boosted:
            score *= SINGLE_USE_DAMPING
        scores[term] = round(score, 4)
    return scores
