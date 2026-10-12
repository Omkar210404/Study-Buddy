"""The daily review queue: which cards to show today, and in what order.

1. Cards reviewed before whose due date has arrived, most overdue first.
2. New cards, at most `new_per_day` per deck per day.
3. Cards rated Again earlier today, so they are seen once more before the session ends.
"""

from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.scheduler.sm2 import AGAIN
from app.storage.models import Card, Review


def new_cards_left(session: Session, deck_id: int, today: date, new_per_day: int) -> int:
    introduced = session.scalar(
        select(func.count()).select_from(Review).where(
            Review.deck_id == deck_id, Review.review_date == today,
            Review.was_new.is_(True), Review.scheduled.is_(True))
    ) or 0
    return max(0, new_per_day - introduced)


def build_queue(session: Session, today: date, new_per_day: int, deck_id: int | None = None) -> list[Card]:
    query = select(Card).order_by(Card.due_date, Card.id)
    if deck_id is not None:
        query = query.where(Card.deck_id == deck_id)
    cards = list(session.scalars(query))

    due = [card for card in cards if not card.is_new and card.due_date <= today]

    new_by_deck: dict[int, list[Card]] = defaultdict(list)
    for card in cards:
        if card.is_new:
            new_by_deck[card.deck_id].append(card)
    new: list[Card] = []
    for deck, deck_cards in new_by_deck.items():
        allowance = new_cards_left(session, deck, today, new_per_day)
        new.extend(sorted(deck_cards, key=lambda card: card.id)[:allowance])
    new.sort(key=lambda card: card.id)

    # The latest review of a card today decides whether it still needs another look.
    latest: dict[int, Review] = {}
    for review in session.scalars(select(Review).where(Review.review_date == today).order_by(Review.id)):
        if review.card_id is not None:
            latest[review.card_id] = review
    by_id = {card.id: card for card in cards}
    again = sorted((review for review in latest.values() if review.rating == AGAIN), key=lambda r: r.id)
    relearn = [by_id[review.card_id] for review in again
               if review.card_id in by_id and by_id[review.card_id].due_date > today]

    return due + new + relearn
