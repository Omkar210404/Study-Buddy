"""Multiple-choice questions. The wrong options are other cards' answers from the same deck.

Nothing is generated: a distractor is always a real answer to a different card. The caller
passes only cards from one deck, and a seed, so the same seed always gives the same question.
"""

import random
from dataclasses import dataclass

from app.quiz.similarity import normalise_answer

DEFAULT_DISTRACTORS = 3
SIMILAR_LENGTH_WORDS = 2


@dataclass(frozen=True)
class QuizCard:
    card_id: int
    kind: str
    front: str
    back: str


@dataclass(frozen=True)
class MCQuestion:
    card_id: int
    prompt: str
    options: tuple[str, ...]
    correct_index: int

    @property
    def correct(self) -> str:
        return self.options[self.correct_index]


def _is_numeric(text: str) -> bool:
    return any(ch.isdigit() for ch in text) and not any(ch.isalpha() for ch in text)


def pick_distractors(target: QuizCard, pool: list[QuizCard], rng: random.Random,
                     count: int = DEFAULT_DISTRACTORS) -> list[str]:
    """Up to `count` answers from other cards, never equal to the right answer or to each other.

    Candidates that look like the right answer are preferred, in this order: number vs words,
    same card kind, similar length. Among equally close candidates the pick is random.
    """
    correct_key = normalise_answer(target.back)
    question_text = f" {normalise_answer(target.front)} "
    candidates: dict[str, QuizCard] = {}
    for card in sorted(pool, key=lambda c: c.card_id):
        key = normalise_answer(card.back)
        if card.card_id == target.card_id or not key or key == correct_key or key in candidates:
            continue
        if f" {key} " in question_text:
            continue  # the question already shows this text, so it cannot be the missing answer
        candidates[key] = card

    target_words = len(target.back.split())

    def distance(card: QuizCard) -> tuple[bool, bool, bool]:
        return (
            _is_numeric(card.back) != _is_numeric(target.back),
            card.kind != target.kind,
            abs(len(card.back.split()) - target_words) > SIMILAR_LENGTH_WORDS,
        )

    # Shuffle, then a stable sort: closer candidates always win, ties are broken at random.
    shuffled = list(candidates.values())
    rng.shuffle(shuffled)
    shuffled.sort(key=distance)
    return [card.back for card in shuffled[:count]]


def build_question(target: QuizCard, pool: list[QuizCard], seed: int,
                   count: int = DEFAULT_DISTRACTORS) -> MCQuestion | None:
    """None when the deck has no other distinct answer to offer as a wrong option."""
    rng = random.Random(seed)
    distractors = pick_distractors(target, pool, rng, count)
    if not distractors:
        return None
    options = distractors + [target.back]
    rng.shuffle(options)
    return MCQuestion(card_id=target.card_id, prompt=target.front, options=tuple(options),
                      correct_index=options.index(target.back))
