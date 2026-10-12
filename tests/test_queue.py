from datetime import datetime, timedelta

from app import services
from app.scheduler.queue import build_queue, new_cards_left
from app.scheduler.sm2 import AGAIN, EASY, GOOD
from tests.conftest import NOW, TODAY, add_card


def make_deck(session, name="Deck"):
    return services.create_deck(session, name, "", NOW)


def fronts(cards):
    return [card.front for card in cards]


def test_new_cards_are_due_on_the_day_they_are_made(session):
    deck = make_deck(session)
    add_card(session, deck, "Q1"), add_card(session, deck, "Q2")
    assert fronts(build_queue(session, TODAY, new_per_day=20)) == ["Q1", "Q2"]


def test_new_cards_are_limited_per_day_and_the_limit_counts_what_was_done(session):
    deck = make_deck(session)
    cards = [add_card(session, deck, f"Q{n}") for n in range(5)]
    assert fronts(build_queue(session, TODAY, new_per_day=3)) == ["Q0", "Q1", "Q2"]

    services.rate_card(session, cards[0], GOOD, NOW)
    services.rate_card(session, cards[1], GOOD, NOW)
    assert new_cards_left(session, deck.id, TODAY, 3) == 1
    assert fronts(build_queue(session, TODAY, new_per_day=3)) == ["Q2"]

    tomorrow = TODAY + timedelta(days=1)
    assert new_cards_left(session, deck.id, tomorrow, 3) == 3
    # tomorrow: the two cards learned today come first (they are due), then three new ones
    assert fronts(build_queue(session, tomorrow, new_per_day=3)) == ["Q0", "Q1", "Q2", "Q3", "Q4"]


def test_reviewed_cards_return_only_when_due_and_most_overdue_first(session):
    deck = make_deck(session)
    early = add_card(session, deck, "early")
    late = add_card(session, deck, "late")
    services.rate_card(session, early, GOOD, NOW)                       # due in 1 day
    services.rate_card(session, late, GOOD, NOW)
    services.rate_card(session, late, GOOD, NOW + timedelta(days=1))    # second success: due 6 days later

    assert build_queue(session, TODAY + timedelta(days=1), 20) == [early]
    assert build_queue(session, TODAY + timedelta(days=6), 20) == [early]
    assert build_queue(session, TODAY + timedelta(days=7), 20) == [early, late]


def test_a_card_rated_again_comes_back_at_the_end_of_the_session(session):
    deck = make_deck(session)
    first, second = add_card(session, deck, "first"), add_card(session, deck, "second")

    services.rate_card(session, first, AGAIN, NOW)
    assert first.due_date == TODAY + timedelta(days=1)
    assert build_queue(session, TODAY, 20) == [second, first]

    services.rate_card(session, second, EASY, NOW)
    assert build_queue(session, TODAY, 20) == [first]


def test_repeat_ratings_after_again_do_not_reschedule(session):
    deck = make_deck(session)
    card = add_card(session, deck)
    first = services.rate_card(session, card, AGAIN, NOW)
    state = (card.ease_factor, card.repetitions, card.interval_days, card.due_date)
    assert first.scheduled and first.was_new
    assert state == (2.18, 0, 1, TODAY + timedelta(days=1))

    later = NOW + timedelta(minutes=5)
    again = services.rate_card(session, card, AGAIN, later)
    assert not again.scheduled
    assert (card.ease_factor, card.repetitions, card.interval_days, card.due_date) == state
    assert build_queue(session, TODAY, 20) == [card]  # still needs another look

    good = services.rate_card(session, card, GOOD, later + timedelta(minutes=5))
    assert not good.scheduled
    assert (card.ease_factor, card.repetitions, card.interval_days, card.due_date) == state
    assert build_queue(session, TODAY, 20) == []      # seen and remembered: done for today
    assert build_queue(session, TODAY + timedelta(days=1), 20) == [card]


def test_lapses_count_forgotten_cards_but_not_a_first_miss(session):
    deck = make_deck(session)
    card = add_card(session, deck)
    services.rate_card(session, card, AGAIN, NOW)
    assert card.lapses == 0
    services.rate_card(session, card, GOOD, NOW + timedelta(days=1))
    services.rate_card(session, card, AGAIN, NOW + timedelta(days=2))
    assert card.lapses == 1


def test_queue_can_be_limited_to_one_deck_and_the_new_limit_is_per_deck(session):
    one, two = make_deck(session, "One"), make_deck(session, "Two")
    for n in range(3):
        add_card(session, one, f"one-{n}")
        add_card(session, two, f"two-{n}")
    assert fronts(build_queue(session, TODAY, 2, deck_id=two.id)) == ["two-0", "two-1"]
    assert len(build_queue(session, TODAY, 2)) == 4


def test_review_rows_record_the_state_before_and_after(session):
    deck = make_deck(session)
    card = add_card(session, deck)
    entry = services.rate_card(session, card, EASY, datetime(2026, 10, 12, 21, 30))
    assert (entry.ease_before, entry.ease_after) == (2.5, 2.6)
    assert (entry.interval_before, entry.interval_after) == (0, 1)
    assert entry.review_date == TODAY and entry.deck_id == deck.id and entry.rating == EASY
