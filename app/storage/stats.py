"""Progress numbers. Everything is counted from the learner's own rows in the database.

Retention for a deck = of the scheduled reviews of cards that had been reviewed before, the
share that was not rated Again. First-ever reviews of a card are left out (there was nothing to
retain yet), and so are same-day repeats after Again.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.scheduler.queue import build_queue
from app.scheduler.sm2 import AGAIN
from app.storage.models import Card, Deck, QuizAttempt, Review

DAYS_SHOWN = 30


@dataclass(frozen=True)
class DayCount:
    day: date
    count: int


@dataclass(frozen=True)
class DeckProgress:
    deck_id: int
    name: str
    cards: int
    due_today: int
    retention_reviews: int
    retention_remembered: int
    quiz_attempts: int
    quiz_correct: int

    @property
    def retention_percent(self) -> int | None:
        if not self.retention_reviews:
            return None
        return round(100 * self.retention_remembered / self.retention_reviews)

    @property
    def quiz_percent(self) -> int | None:
        if not self.quiz_attempts:
            return None
        return round(100 * self.quiz_correct / self.quiz_attempts)


@dataclass(frozen=True)
class Progress:
    today: date
    due_today: int
    total_cards: int
    total_reviews: int
    reviews_today: int
    days: list[DayCount] = field(default_factory=list)
    decks: list[DeckProgress] = field(default_factory=list)

    @property
    def busiest_day(self) -> int:
        return max((day.count for day in self.days), default=0)

    @property
    def reviews_in_window(self) -> int:
        return sum(day.count for day in self.days)


def reviews_per_day(session: Session, today: date, days: int = DAYS_SHOWN) -> list[DayCount]:
    """One entry per calendar day, oldest first, zero-filled. Every rating press counts once."""
    start = today - timedelta(days=days - 1)
    rows = session.execute(
        select(Review.review_date, func.count()).where(Review.review_date >= start,
                                                       Review.review_date <= today)
        .group_by(Review.review_date)
    ).all()
    counts = {day: count for day, count in rows}
    return [DayCount(start + timedelta(days=offset), counts.get(start + timedelta(days=offset), 0))
            for offset in range(days)]


def deck_progress(session: Session, deck: Deck, today: date, new_per_day: int) -> DeckProgress:
    retention = select(func.count()).select_from(Review).where(
        Review.deck_id == deck.id, Review.scheduled.is_(True), Review.was_new.is_(False))
    quiz = select(func.count()).select_from(QuizAttempt).where(QuizAttempt.deck_id == deck.id)
    return DeckProgress(
        deck_id=deck.id,
        name=deck.name,
        cards=session.scalar(select(func.count()).select_from(Card).where(Card.deck_id == deck.id)) or 0,
        due_today=len(build_queue(session, today, new_per_day, deck.id)),
        retention_reviews=session.scalar(retention) or 0,
        retention_remembered=session.scalar(retention.where(Review.rating != AGAIN)) or 0,
        quiz_attempts=session.scalar(quiz) or 0,
        quiz_correct=session.scalar(quiz.where(QuizAttempt.correct.is_(True))) or 0,
    )


def progress(session: Session, today: date, new_per_day: int) -> Progress:
    decks = [deck_progress(session, deck, today, new_per_day)
             for deck in session.scalars(select(Deck).order_by(Deck.name))]
    days = reviews_per_day(session, today)
    return Progress(
        today=today,
        due_today=sum(deck.due_today for deck in decks),
        total_cards=sum(deck.cards for deck in decks),
        total_reviews=session.scalar(select(func.count()).select_from(Review)) or 0,
        reviews_today=days[-1].count,
        days=days,
        decks=decks,
    )
