"""Offline card generation: extractive, deterministic, no network and no model.

Two kinds of card come out of each passage:
- definition cards, from sentences shaped like "X is a ...", "X refers to ...", "... is called X"
- cloze cards, where one key term in a sentence is replaced by a blank

Every card's supporting quote is the sentence it was built from, copied verbatim, so these cards
pass the grounding validator by construction. The quality is basic: the code matches patterns
and counts words, it does not understand the notes.
"""

import re
from dataclasses import dataclass

from app.generation.terms import NUMBER_SCORE, Token, is_number, phrase_pairs, score_terms, tokens
from app.grounding.validator import MAX_QUOTE_CHARS
from app.ingestion.splitter import Passage
from app.schemas import CardDraft
from app.text import collapse_ws, is_bullet, sentence_spans, strip_bullet, strip_markers

MAX_CARDS_PER_PASSAGE = 3
# A glossary list can define more terms than that; definitions get a little extra room.
EXTRA_DEFINITIONS = 2
MIN_SENTENCE_WORDS = 6
MAX_SENTENCE_WORDS = 40
MIN_WORDS_LEFT_AFTER_BLANK = 5
REUSE_PENALTY = 0.5  # each time a term has been blanked already, its score halves
NUMBER_LEAD = 1.05
BLANK = "_____"

_PRONOUNS = {
    "it", "this", "that", "these", "those", "there", "here", "he", "she", "they", "we", "you", "i",
    "what", "which", "who", "one", "each", "such", "another", "its", "their", "both", "some", "all",
}
_CALLED_BAD_START = {"it", "this", "that", "these", "those", "they", "there", "here", "he", "she",
                     "we", "you", "i", "which", "what", "who"}
_CALLED_BAD_WORDS = {"is", "are", "was", "were", "which"}
_GLOSSARY_STOP = {"note", "example", "examples", "tip", "warning", "remember", "important",
                  "summary", "hint", "caution", "e.g", "todo", "question", "answer"}

_TERM = r"(?P<term>[A-Za-z0-9][\w/'+.-]*(?:\s+[\w/'+().-]+){0,4}?)"
_ART = r"(?:(?P<art>[Tt]he|[Aa]n?)\s+)?"
_INTRO = r"(?:(?:In|On|For|With|Within)\s+[^,]{2,40},\s+)?"
_SUBJECT = rf"^{_INTRO}{_ART}{_TERM}"

_CALLED_RE = re.compile(
    r"^(?P<def>.{15,}?)\s+(?:is|are)\s+(?:called|known\s+as|referred\s+to\s+as)\s+"
    r"(?:(?:a|an|the)\s+)?(?P<term>[^,;]{2,50})$"
)
_SUBJECT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(rf"{_SUBJECT}\s+(?P<verb>is|are)\s+defined\s+as\s+(?P<def>.+)$"), "How {verb} {subject} defined?"),
    (re.compile(rf"{_SUBJECT}\s+refers?\s+to\s+(?P<def>.+)$"), "What does {subject} refer to?"),
    (re.compile(rf"{_SUBJECT}\s+stands\s+for\s+(?P<def>.+)$"), "What does {subject} stand for?"),
    (re.compile(rf"{_SUBJECT}\s+means\s+(?P<def>.+)$"), "What does {subject} mean?"),
    (re.compile(rf"{_SUBJECT}\s+(?P<verb>is|are)\s+(?P<def>(?:a|an|the|one\s+of|any)\s+.+)$"),
     "What {verb} {subject}?"),
]
_GLOSSARY_RE = re.compile(r"^(?P<term>[^:—–]{2,60}?)\s*(?::|\s[—–-]\s)\s*(?P<def>\S.{14,})$")


@dataclass(frozen=True)
class _Sentence:
    raw: str    # verbatim text from the passage: this is the supporting quote
    clean: str  # bullet and Markdown markers removed, whitespace collapsed: used for card text


def _sentences(passage_text: str) -> list[_Sentence]:
    out = []
    for start, end in sentence_spans(passage_text):
        raw = passage_text[start:end]
        clean = collapse_ws(strip_bullet(strip_markers(raw)))
        if clean and not clean.startswith(("|", "```", "#")):
            out.append(_Sentence(raw, clean))
    return out


def _usable(sentence: _Sentence) -> bool:
    count = len(sentence.clean.split())
    return (
        MIN_SENTENCE_WORDS <= count <= MAX_SENTENCE_WORDS
        and len(collapse_ws(sentence.raw)) <= MAX_QUOTE_CHARS
        and not sentence.clean.endswith("?")
    )


def _valid_term(term: str) -> bool:
    parts = term.split()
    return bool(parts) and len(parts) <= 5 and "," not in term and parts[0].lower() not in _PRONOUNS


def _capitalise(text: str) -> str:
    return text[:1].upper() + text[1:]


def _lower_article(text: str) -> str:
    first, _, rest = text.partition(" ")
    determiners = {"a", "an", "the", "each", "every", "any", "all", "some"}
    return f"{first.lower()} {rest}" if first.lower() in determiners and rest else text


def _first_clause(definition: str) -> str:
    """Keep the definition itself and drop an explanation added after a colon or semicolon."""
    head = re.split(r"[:;]\s", definition, maxsplit=1)[0].strip()
    return head if len(head.split()) >= 3 else definition


def _sentence_case_term(term: str, lower_words: frozenset[str]) -> str:
    """"Latency refers to ..." -> "latency", but only if the notes also write the word in lower case."""
    first = term.split()[0]
    if first[0].isupper() and first[1:].islower() and first.lower() in lower_words:
        return term[0].lower() + term[1:]
    return term


def find_definition(sentence: str, glossary_line: bool = False,
                    lower_words: frozenset[str] = frozenset()) -> tuple[str, str] | None:
    """Return (front, back) if the sentence defines a term, else None.

    `sentence` is clean text. `glossary_line` is True for list items and lines that open with a
    bold term, where "Term: explanation" is read as a definition. `lower_words` are words the
    notes write in lower case somewhere, used to undo sentence-initial capitals.
    """
    body = sentence.rstrip(".").strip()
    if not 5 <= len(body.split()) <= MAX_SENTENCE_WORDS + 5:
        return None

    match = _CALLED_RE.match(body)
    if match:
        term, definition = match.group("term").strip(), match.group("def").strip()
        parts = definition.lower().split()
        if (len(term.split()) <= 5 and "," not in definition
                and parts[0] not in _CALLED_BAD_START and not _CALLED_BAD_WORDS & set(parts)):
            return f"What do we call {_lower_article(definition)}?", _capitalise(term)

    for pattern, template in _SUBJECT_PATTERNS:
        match = pattern.match(body)
        if not match:
            continue
        term, definition = match.group("term").strip(), _first_clause(match.group("def").strip())
        if not _valid_term(term) or len(definition.split()) < 3:
            continue
        article = match.group("art")
        subject = f"{article.lower()} {term}" if article else _sentence_case_term(term, lower_words)
        verb = match.groupdict().get("verb") or "is"
        return template.format(subject=subject, verb=verb), _capitalise(definition)

    if glossary_line:
        match = _GLOSSARY_RE.match(body)
        if match:
            term, definition = match.group("term").strip(), match.group("def").strip()
            if _valid_term(term) and term.lower() not in _GLOSSARY_STOP and len(definition.split()) >= 3:
                return f"Define: {term}", _capitalise(definition)
    return None


@dataclass(frozen=True)
class _Blank:
    score: float
    start: int
    surface: str
    key: str


def _best_blank(sentence: str, scores: dict[str, float], used: dict[str, int]) -> _Blank | None:
    """The highest-scoring term in the sentence; the earliest one wins a tie."""
    sentence_tokens = tokens(sentence)
    spans: list[tuple[str, Token, Token]] = [(t.key, t, t) for t in sentence_tokens]
    spans += [(f"{a.key} {b.key}", a, b) for a, b in phrase_pairs(sentence_tokens, sentence)]

    # A figure in a sentence is usually the fact worth recalling, so it outranks the words around it.
    top_word = max((scores.get(key, 0.0) for key, _first, _last in spans), default=0.0)
    number_score = max(NUMBER_SCORE, top_word * NUMBER_LEAD)

    best: _Blank | None = None
    for key, first, last in spans:
        if first is last and is_number(first.text):
            # Skip list numbering and single digits; "443" or "65,535" are worth asking about.
            base = number_score if len(first.text) >= 2 else 0.0
            key = f"#{first.text}"
        else:
            base = scores.get(key, 0.0)
        score = base * (REUSE_PENALTY ** used.get(key, 0))
        if score <= 0:
            continue
        candidate = _Blank(score, first.start, sentence[first.start:last.end], key)
        if best is None or (candidate.score, -candidate.start) > (best.score, -best.start):
            best = candidate
    return best


def make_cloze(sentence: str, surface: str) -> str | None:
    """Blank every occurrence of the term. None if too little of the sentence would be left."""
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(surface)}(?![A-Za-z0-9])", re.IGNORECASE)
    front = pattern.sub(BLANK, sentence)
    remaining = [word for word in front.split() if BLANK not in word]
    if BLANK not in front or len(remaining) < MIN_WORDS_LEFT_AFTER_BLANK:
        return None
    return front


def section_tag(title: str | None) -> list[str]:
    if not title:
        return []
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:30].strip("-")
    return [slug] if slug else []


def generate_offline(passages: list[Passage], max_per_passage: int = MAX_CARDS_PER_PASSAGE) -> list[CardDraft]:
    """Definition cards first, then cloze cards, at most `max_per_passage` per passage."""
    headings = sorted({p.section_title for p in passages if p.section_title})
    scores = score_terms([p.text for p in passages], headings)
    lower_words = frozenset(
        t.text for p in passages for t in tokens(strip_markers(p.text)) if t.text.islower()
    )
    used: dict[str, int] = {}
    seen_fronts: set[str] = set()
    drafts: list[CardDraft] = []

    def add(passage: Passage, kind: str, front: str, back: str, quote: str) -> bool:
        if front.lower() in seen_fronts:
            return False
        seen_fronts.add(front.lower())
        drafts.append(CardDraft(kind=kind, front=front, back=back, quote=quote,
                                passage_ordinal=passage.ordinal, tags=section_tag(passage.section_title)))
        return True

    for passage in passages:
        made = 0
        remaining: list[_Sentence] = []
        for sentence in _sentences(passage.text):
            found = None
            if made < max_per_passage + EXTRA_DEFINITIONS and len(collapse_ws(sentence.raw)) <= MAX_QUOTE_CHARS:
                glossary = is_bullet(sentence.raw) or sentence.raw.lstrip().startswith("**")
                found = find_definition(sentence.clean, glossary_line=glossary, lower_words=lower_words)
            if found and add(passage, "definition", found[0], found[1], sentence.raw):
                made += 1
            elif _usable(sentence):
                remaining.append(sentence)

        clozes: list[tuple[int, str, str, str]] = []
        while made + len(clozes) < max_per_passage and remaining:
            ranked = [(index, _best_blank(s.clean, scores, used)) for index, s in enumerate(remaining)]
            ranked = [(index, blank) for index, blank in ranked if blank is not None]
            if not ranked:
                break
            index, blank = max(ranked, key=lambda item: (item[1].score, -item[0]))
            sentence = remaining.pop(index)
            used[blank.key] = used.get(blank.key, 0) + 1
            front = make_cloze(sentence.clean, blank.surface)
            if front:
                clozes.append((passage.text.index(sentence.raw), front, blank.surface, sentence.raw))
        for _position, front, back, quote in sorted(clozes):
            add(passage, "cloze", front, back, quote)
    return drafts
