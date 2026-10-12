"""Progress numbers from a small, known review history."""

from datetime import timedelta

from app import services
from app.scheduler.sm2 import AGAIN, GOOD, HARD
from app.storage.stats import DAYS_SHOWN, progress, reviews_per_day
from tests.conftest import NOW, TODAY, add_card

DAY = timedelta(days=1)


def build_history(session):
    """Deck A: three cards studied over three days. Deck B: one card, never reviewed."""
    deck_a = services.create_deck(session, "A deck", "", NOW)
    deck_b = services.create_deck(session, "B deck", "", NOW)
    start = NOW - 2 * DAY
    c1 = add_card(session, deck_a, "Q1", created=start)
    c2 = add_card(session, deck_a, "Q2", created=start)
    c3 = add_card(session, deck_a, "Q3", created=start)
    add_card(session, deck_b, "Q4", created=start)

    # two days ago: three first reviews (never part of retention)
    services.rate_card(session, c1, GOOD, start)
    services.rate_card(session, c2, GOOD, start)
    services.rate_card(session, c3, AGAIN, start)
    services.rate_card(session, c3, GOOD, start + timedelta(minutes=1))  # same-day repeat, unscheduled
    # yesterday: all three are due again; c2 is forgotten
    services.rate_card(session, c1, GOOD, start + DAY)
    services.rate_card(session, c2, AGAIN, start + DAY)
    services.rate_card(session, c3, HARD, start + DAY)
    # today: c2 (forgotten yesterday) and c3 (first success yesterday) are due; c1 is due in 5 days
    services.rate_card(session, c2, GOOD, NOW)
    session.commit()
    return deck_a, deck_b


def test_reviews_per_day_counts_every_rating_press(session):
    build_history(session)
    days = reviews_per_day(session, TODAY)
    assert len(days) == DAYS_SHOWN
    assert days[-1].day == TODAY and days[0].day == TODAY - timedelta(days=DAYS_SHOWN - 1)
    assert [d.count for d in days[-3:]] == [4, 3, 1]
    assert sum(d.count for d in days[:-3]) == 0


def test_retention_uses_only_scheduled_reviews_of_cards_seen_before(session):
    deck_a, deck_b = build_history(session)
    result = progress(session, TODAY, new_per_day=20)
    by_name = {deck.name: deck for deck in result.decks}

    a = by_name["A deck"]
    # counted: yesterday's three reviews and today's one = 4; remembered: all but c2's Again = 3
    assert (a.retention_reviews, a.retention_remembered, a.retention_percent) == (4, 3, 75)
    assert a.cards == 3

    b = by_name["B deck"]
    assert (b.retention_reviews, b.retention_percent) == (0, None)  # no history, no number


def test_due_today_and_totals(session):
    build_history(session)
    result = progress(session, TODAY, new_per_day=20)
    by_name = {deck.name: deck for deck in result.decks}
    assert by_name["A deck"].due_today == 1   # c3: Hard yesterday was its first success, so 1 day
    assert by_name["B deck"].due_today == 1   # its one new card
    assert result.due_today == 2
    assert result.total_cards == 4 and result.total_reviews == 8
    assert result.reviews_today == 1 and result.busiest_day == 4 and result.reviews_in_window == 8


def test_quiz_accuracy_is_counted_per_deck_and_never_moves_the_schedule(session):
    deck = services.create_deck(session, "Quiz deck", "", NOW)
    card = add_card(session, deck)
    before = (card.ease_factor, card.interval_days, card.due_date, card.last_reviewed_at)
    services.record_quiz_attempt(session, card, "mc", True, None, NOW)
    services.record_quiz_attempt(session, card, "typed", False, 0.4, NOW)
    services.record_quiz_attempt(session, card, "typed", True, 0.91, NOW)
    result = progress(session, TODAY, new_per_day=20).decks[0]
    assert (result.quiz_attempts, result.quiz_correct, result.quiz_percent) == (3, 2, 67)
    assert (card.ease_factor, card.interval_days, card.due_date, card.last_reviewed_at) == before
    assert result.retention_reviews == 0


def test_empty_database_reports_nothing_rather_than_zeros_dressed_as_results(session):
    result = progress(session, TODAY, new_per_day=20)
    assert result.decks == [] and result.due_today == 0 and result.total_reviews == 0
    assert result.busiest_day == 0
