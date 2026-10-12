"""Use cases. The one place where ingestion, generation, grounding, scheduling and storage meet.

The web layer calls these functions and renders what they return. Nothing here reads the clock:
the current time is always passed in.
"""

from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import IngestionError, StudyBuddyError
from app.generation.llm import generate_llm
from app.generation.offline import generate_offline
from app.grounding import REASONS, check_quote, question_key
from app.ingestion.extract import ExtractedText, from_file
from app.ingestion.splitter import Passage, split_passages
from app.llm.base import LLMProvider
from app.scheduler.sm2 import CardState, review
from app.schemas import CardDraft, Rejection
from app.storage.models import (
    Card,
    Deck,
    GenerationRun,
    PassageRow,
    QuizAttempt,
    RejectedCard,
    Review,
    Source,
    Tag,
)

SAMPLE_NOTES = Path(__file__).resolve().parent.parent / "sample_notes" / "networking-basics.md"
SAMPLE_DECK_NAME = "Networking basics (sample)"
MAX_TAG_LENGTH = 40


class CardEditError(StudyBuddyError):
    """An edit that would leave the card without a real supporting quote, or otherwise invalid."""


# --- decks and sources ------------------------------------------------------------------------

def create_deck(session: Session, name: str, description: str, now: datetime) -> Deck:
    name = " ".join(name.split())
    if not name:
        raise StudyBuddyError("Give the deck a name.")
    deck = Deck(name=name[:120], description=description.strip(), created_at=now)
    session.add(deck)
    session.flush()
    return deck


def import_source(session: Session, deck: Deck, extracted: ExtractedText, title: str,
                  filename: str | None, now: datetime) -> Source:
    passages = split_passages(extracted.text, extracted.page_starts)
    if not passages:
        raise IngestionError("No passages could be found in these notes.")
    title = " ".join(title.split()) or (filename or "Pasted notes")
    source = Source(deck_id=deck.id, title=title[:200], kind=extracted.kind, filename=filename,
                    text=extracted.text, created_at=now)
    source.passages = [
        PassageRow(ordinal=p.ordinal, section_title=p.section_title, text=p.text,
                   start_char=p.start_char, end_char=p.end_char, page=p.page)
        for p in passages
    ]
    session.add(source)
    session.flush()
    return source


def to_passages(rows: list[PassageRow]) -> list[Passage]:
    return [Passage(ordinal=r.ordinal, section_title=r.section_title, text=r.text,
                    start_char=r.start_char, end_char=r.end_char, page=r.page) for r in rows]


# --- tags -------------------------------------------------------------------------------------

def clean_tags(raw: str | list[str]) -> list[str]:
    """Lower-case, hyphenated, unique tag names.

    A string is split on commas if it has any ("week 1, exam" gives week-1 and exam),
    otherwise on spaces ("ports exam" gives ports and exam).
    """
    if isinstance(raw, str):
        parts = raw.split(",") if "," in raw else raw.split()
    else:
        parts = raw
    names: list[str] = []
    for part in parts:
        name = "-".join(part.lower().split())[:MAX_TAG_LENGTH].strip("-")
        if name and name not in names:
            names.append(name)
    return names


def _tags(session: Session, names: list[str]) -> list[Tag]:
    tags = []
    for name in clean_tags(names):
        tag = session.scalar(select(Tag).where(Tag.name == name))
        if tag is None:
            tag = Tag(name=name)
            session.add(tag)
            session.flush()
        tags.append(tag)
    return tags


# --- generation -------------------------------------------------------------------------------

def _store(session: Session, run: GenerationRun, source: Source, drafts: list[CardDraft],
           earlier_rejections: list[Rejection], origin: str, now: datetime) -> None:
    """Run every draft through the grounding validator; keep what passes, record what does not."""
    rows = {row.ordinal: row for row in source.passages}
    seen = {question_key(card.front) for card in source.deck.cards}
    rejections = list(earlier_rejections)
    accepted = 0

    for draft in drafts:
        row = rows[draft.passage_ordinal]
        result = check_quote(draft.quote, row.text)
        reason = result.reason
        if result.ok and question_key(draft.front) in seen:
            reason = "duplicate"
        if reason:
            rejections.append(Rejection(reason=reason, passage_ordinal=draft.passage_ordinal,
                                        front=draft.front, back=draft.back, quote=draft.quote))
            continue
        seen.add(question_key(draft.front))
        session.add(Card(
            deck_id=source.deck_id, passage_id=row.id, run_id=run.id, kind=draft.kind, origin=origin,
            front=draft.front, back=draft.back,
            supporting_quote=result.quote, source_passage=row.text,
            quote_start=result.start, quote_end=result.end,
            section_title=row.section_title, source_title=source.title,
            due_date=now.date(), created_at=now, updated_at=now,
            tags=_tags(session, draft.tags),
        ))
        accepted += 1

    for rejection in rejections:
        row = rows.get(rejection.passage_ordinal)
        run.rejections.append(RejectedCard(
            passage_ordinal=rejection.passage_ordinal,
            section_title=row.section_title if row else None,
            reason=rejection.reason, front=rejection.front, back=rejection.back,
            quote=rejection.quote, detail=rejection.detail,
        ))
    run.accepted = accepted
    run.rejected = len(rejections)
    run.proposed = accepted + len(rejections)
    session.flush()
    session.refresh(source.deck)


def _new_run(session: Session, source: Source, mode: str, now: datetime) -> GenerationRun:
    run = GenerationRun(deck_id=source.deck_id, source_id=source.id, source_title=source.title,
                        mode=mode, passages_total=len(source.passages), created_at=now)
    session.add(run)
    session.flush()
    return run


def generate_offline_cards(session: Session, source: Source, now: datetime) -> GenerationRun:
    run = _new_run(session, source, "offline", now)
    run.passages_used = len(source.passages)
    drafts = generate_offline(to_passages(source.passages))
    _store(session, run, source, drafts, [], "offline", now)
    return run


def _passages_for_llm(session: Session, source: Source, limit: int) -> list[PassageRow]:
    """The next passages that have no model-written cards yet, so a second run continues the notes."""
    done = set(session.scalars(
        select(Card.passage_id).where(Card.deck_id == source.deck_id, Card.origin.in_(("llm", "mock")))
    ))
    pending = [row for row in source.passages if row.id not in done]
    return (pending or list(source.passages))[:limit]


async def generate_llm_cards(session: Session, source: Source, provider: LLMProvider,
                             settings: Settings, now: datetime) -> GenerationRun:
    """Only the passages chosen here are sent to the provider. Nothing else leaves the machine."""
    rows = _passages_for_llm(session, source, settings.llm_max_passages_per_run)
    result = await generate_llm(provider, to_passages(rows), max_cards=settings.llm_cards_per_passage)
    run = _new_run(session, source, "llm", now)
    run.provider, run.model = provider.name, provider.model
    run.passages_used = len(rows)
    origin = "mock" if provider.name == "mock" else "llm"
    _store(session, run, source, result.drafts, result.rejections, origin, now)
    return run


def load_sample_deck(session: Session, now: datetime) -> Deck:
    """Create the demo deck from the bundled sample notes, once."""
    existing = session.scalar(select(Deck).where(Deck.name == SAMPLE_DECK_NAME))
    if existing is not None:
        return existing
    deck = create_deck(session, SAMPLE_DECK_NAME,
                       "Short synthetic notes written for this project. Safe to delete.", now)
    extracted = from_file(SAMPLE_NOTES.name, SAMPLE_NOTES.read_bytes(), 5 * 1024 * 1024)
    source = import_source(session, deck, extracted, "Networking basics", SAMPLE_NOTES.name, now)
    generate_offline_cards(session, source, now)
    return deck


# --- review and quiz --------------------------------------------------------------------------

def rate_card(session: Session, card: Card, rating: int, now: datetime) -> Review:
    """Record a rating. SM-2 moves the schedule only when the card was actually due.

    A card rated Again is shown again later the same day. By then it is already due tomorrow,
    so those repeat ratings are logged with scheduled=False and leave ease and interval alone.
    """
    today = now.date()
    before = CardState(card.ease_factor, card.repetitions, card.interval_days)
    was_new = card.is_new
    scheduled = card.due_date <= today
    if scheduled:
        outcome = review(before, rating, today)
        card.ease_factor = outcome.state.ease_factor
        card.repetitions = outcome.state.repetitions
        card.interval_days = outcome.state.interval_days
        card.due_date = outcome.due_date
        if outcome.lapsed and not was_new:
            card.lapses += 1
    elif rating not in (1, 2, 3, 4):
        raise ValueError(f"rating must be 1 (Again) to 4 (Easy), got {rating!r}")
    card.last_reviewed_at = now
    entry = Review(card_id=card.id, deck_id=card.deck_id, reviewed_at=now, review_date=today,
                   rating=rating, scheduled=scheduled, was_new=was_new,
                   ease_before=before.ease_factor, ease_after=card.ease_factor,
                   interval_before=before.interval_days, interval_after=card.interval_days)
    session.add(entry)
    session.flush()
    return entry


def record_quiz_attempt(session: Session, card: Card, mode: str, correct: bool,
                        similarity: float | None, now: datetime) -> QuizAttempt:
    """Quiz answers are practice. They are logged for the progress page and never move the schedule."""
    attempt = QuizAttempt(card_id=card.id, deck_id=card.deck_id, mode=mode, correct=correct,
                          similarity=similarity, answered_at=now)
    session.add(attempt)
    session.flush()
    return attempt


# --- editing ----------------------------------------------------------------------------------

def update_card(session: Session, card: Card, front: str, back: str, quote: str,
                tags: str | list[str], now: datetime) -> None:
    """Edit a card. The quote must still be found in the card's stored passage."""
    front, back = front.strip(), back.strip()
    if not front or not back:
        raise CardEditError("A card needs both a question and an answer.")
    result = check_quote(quote, card.source_passage)
    if not result.ok:
        raise CardEditError(f"The supporting quote was not accepted. {REASONS[result.reason]}")
    key = question_key(front)
    clash = session.scalars(select(Card).where(Card.deck_id == card.deck_id, Card.id != card.id))
    if any(question_key(other.front) == key for other in clash):
        raise CardEditError("Another card in this deck already asks that question.")
    card.front, card.back = front, back
    card.supporting_quote, card.quote_start, card.quote_end = result.quote, result.start, result.end
    card.tags = _tags(session, clean_tags(tags))
    card.updated_at = now
    session.flush()
