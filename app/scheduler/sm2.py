"""SM-2 spaced repetition (Wozniak, 1987), with four rating buttons mapped to its 0-5 quality scale.

Pure functions: the caller passes today's date in, nothing here reads a clock or a database.

    quality q:   Again = 2, Hard = 3, Good = 4, Easy = 5
    EF' = max(1.3, EF + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    q < 3:   repetitions = 0, interval = 1 day
    q >= 3:  interval = 1 day (first success), 6 days (second), then round(interval * EF')
             repetitions += 1
    due = today + interval

This is plain SM-2. There are no learning steps, no interval fuzz and no easy bonus, so Hard and
Good give the same interval for the next review and differ only through the ease factor.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4
RATING_LABELS = {AGAIN: "Again", HARD: "Hard", GOOD: "Good", EASY: "Easy"}
QUALITY = {AGAIN: 2, HARD: 3, GOOD: 4, EASY: 5}

INITIAL_EASE = 2.5
MIN_EASE = 1.3
FIRST_INTERVAL = 1
SECOND_INTERVAL = 6


@dataclass(frozen=True)
class CardState:
    ease_factor: float = INITIAL_EASE
    repetitions: int = 0
    interval_days: int = 0


@dataclass(frozen=True)
class ReviewOutcome:
    state: CardState
    due_date: date
    lapsed: bool


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def next_ease(ease_factor: float, quality: int) -> float:
    miss = 5 - quality
    return round(max(MIN_EASE, ease_factor + 0.1 - miss * (0.08 + miss * 0.02)), 4)


def review(state: CardState, rating: int, today: date) -> ReviewOutcome:
    if rating not in QUALITY:
        raise ValueError(f"rating must be 1 (Again) to 4 (Easy), got {rating!r}")
    quality = QUALITY[rating]
    ease = next_ease(state.ease_factor, quality)

    if quality < 3:
        new_state = CardState(ease_factor=ease, repetitions=0, interval_days=FIRST_INTERVAL)
    else:
        if state.repetitions == 0:
            interval = FIRST_INTERVAL
        elif state.repetitions == 1:
            interval = SECOND_INTERVAL
        else:
            interval = max(1, _round_half_up(state.interval_days * ease))
        new_state = CardState(ease_factor=ease, repetitions=state.repetitions + 1, interval_days=interval)

    return ReviewOutcome(
        state=new_state,
        due_date=today + timedelta(days=new_state.interval_days),
        lapsed=quality < 3,
    )


def preview_intervals(state: CardState) -> dict[int, int]:
    """Days until the next review for each button, shown on the buttons before the learner chooses."""
    today = date(2000, 1, 1)  # any date works: only the interval is read
    return {rating: review(state, rating, today).state.interval_days for rating in QUALITY}
