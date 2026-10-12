"""SM-2 against examples worked out by hand (the same table is in PLAN.md and the README)."""

from datetime import date

import pytest

from app.scheduler.sm2 import AGAIN, EASY, GOOD, HARD, CardState, next_ease, preview_intervals, review

TODAY = date(2026, 10, 12)


def test_new_card_defaults():
    assert CardState() == CardState(ease_factor=2.5, repetitions=0, interval_days=0)


def test_hand_calculated_sequence():
    # rating, ease after, repetitions after, interval after
    #   Hard:  2.5 + 0.1 - 2 * (0.08 + 2 * 0.02) = 2.36, and 15 * 2.36 = 35.4 -> 35
    #   Again: 2.36 + 0.1 - 3 * (0.08 + 3 * 0.02) = 2.04, back to a 1-day interval
    #   Easy:  2.04 + 0.1 = 2.14, first success after a lapse -> 1 day
    steps = [
        (GOOD, 2.50, 1, 1),
        (GOOD, 2.50, 2, 6),
        (GOOD, 2.50, 3, 15),
        (HARD, 2.36, 4, 35),
        (AGAIN, 2.04, 0, 1),
        (EASY, 2.14, 1, 1),
        (GOOD, 2.14, 2, 6),
        (GOOD, 2.14, 3, 13),  # 6 * 2.14 = 12.84 -> 13
    ]
    state = CardState()
    for rating, ease, repetitions, interval in steps:
        outcome = review(state, rating, TODAY)
        state = outcome.state
        assert state.ease_factor == pytest.approx(ease)
        assert (state.repetitions, state.interval_days) == (repetitions, interval)
        assert (outcome.due_date - TODAY).days == interval


@pytest.mark.parametrize("rating, change", [(AGAIN, -0.32), (HARD, -0.14), (GOOD, 0.0), (EASY, 0.10)])
def test_ease_change_per_button(rating, change):
    assert review(CardState(), rating, TODAY).state.ease_factor == pytest.approx(2.5 + change)


def test_ease_never_drops_below_the_floor():
    assert next_ease(1.4, 2) == 1.3  # 1.4 - 0.32 = 1.08 -> 1.3
    state = CardState()
    for _ in range(10):
        state = review(state, AGAIN, TODAY).state
    assert state.ease_factor == 1.3


def test_again_resets_progress_and_is_a_lapse():
    learned = CardState(ease_factor=2.5, repetitions=5, interval_days=90)
    outcome = review(learned, AGAIN, TODAY)
    assert outcome.lapsed
    assert outcome.state == CardState(ease_factor=2.18, repetitions=0, interval_days=1)
    assert outcome.due_date == date(2026, 10, 13)
    assert not review(learned, HARD, TODAY).lapsed


def test_interval_rounds_half_up_not_to_even():
    # 5 * 2.5 = 12.5. Python's round() would give 12; SM-2 here gives 13.
    state = CardState(ease_factor=2.5, repetitions=2, interval_days=5)
    assert review(state, GOOD, TODAY).state.interval_days == 13


def test_hard_and_good_share_the_next_interval_on_a_new_card():
    intervals = preview_intervals(CardState())
    assert intervals == {AGAIN: 1, HARD: 1, GOOD: 1, EASY: 1}
    mature = preview_intervals(CardState(ease_factor=2.5, repetitions=3, interval_days=15))
    assert mature == {AGAIN: 1, HARD: 35, GOOD: 38, EASY: 39}  # 15 * 2.36, 15 * 2.5, 15 * 2.6


def test_review_does_not_mutate_and_rejects_bad_ratings():
    state = CardState()
    review(state, GOOD, TODAY)
    assert state == CardState()
    with pytest.raises(ValueError):
        review(state, 5, TODAY)
