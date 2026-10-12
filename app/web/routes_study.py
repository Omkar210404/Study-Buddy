"""Review sessions (SM-2) and quiz mode."""

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import services
from app.quiz.distractors import MCQuestion, QuizCard, build_question
from app.quiz.similarity import CLOSE_THRESHOLD, check_answer, normalise_answer
from app.scheduler.queue import build_queue
from app.scheduler.sm2 import AGAIN, RATING_LABELS, CardState, preview_intervals
from app.storage.models import Card, Deck, QuizAttempt, Review
from app.web.deps import current_time, due_text, get_or_404, get_session, interval_text, render

router = APIRouter()

# Typed answers suit short answers; long definitions are better as multiple choice.
TYPED_MAX_WORDS = 6
QUIZ_MODES = {"mc": "Multiple choice", "typed": "Typed answer"}


# --- review -----------------------------------------------------------------------------------

def review_context(request: Request, session: Session, now: datetime, deck_id: int | None) -> dict:
    today = now.date()
    queue = build_queue(session, today, request.app.state.settings.new_cards_per_day, deck_id)
    done_query = select(func.count()).select_from(Review).where(
        Review.review_date == today, Review.scheduled.is_(True))
    if deck_id is not None:
        done_query = done_query.where(Review.deck_id == deck_id)
    done = session.scalar(done_query) or 0

    card = queue[0] if queue else None
    buttons = []
    if card is not None:
        if card.due_date <= today:
            intervals = preview_intervals(CardState(card.ease_factor, card.repetitions, card.interval_days))
            hints = {rating: interval_text(days) for rating, days in intervals.items()}
            hints[AGAIN] = "again today"
        else:
            # A repeat after Again: the schedule is already set, so the buttons only decide
            # whether the card comes round once more today.
            hints = {rating: due_text(card.due_date, today) for rating in RATING_LABELS}
            hints[AGAIN] = "again today"
        buttons = [(rating, label, hints[rating]) for rating, label in RATING_LABELS.items()]

    return {
        "card": card,
        "buttons": buttons,
        "remaining": len(queue),
        "done": done,
        "deck": session.get(Deck, deck_id) if deck_id is not None else None,
        "deck_id": deck_id,
    }


@router.get("/review")
def review_page(request: Request, deck: int | None = None, session: Session = Depends(get_session),
                now: datetime = Depends(current_time)):
    if deck is not None:
        get_or_404(session, Deck, deck)
    return render(request, "review.html", focus=True, leave_url=f"/decks/{deck}" if deck is not None else "/",
                  **review_context(request, session, now, deck))


@router.post("/review/{card_id}/rate")
def rate(request: Request, card_id: int, rating: int = Form(...), deck: str = Form(""),
         session: Session = Depends(get_session), now: datetime = Depends(current_time)):
    deck_id = int(deck) if deck.strip().isdigit() else None
    card = get_or_404(session, Card, card_id)
    queue = build_queue(session, now.date(), request.app.state.settings.new_cards_per_day, card.deck_id)
    # Ignore a second press for a card that has already left today's queue (a double key press).
    if rating in RATING_LABELS and card in queue:
        services.rate_card(session, card, rating, now)
        session.commit()
    return render(request, "_review_stage.html", **review_context(request, session, now, deck_id))


# --- quiz -------------------------------------------------------------------------------------

def _quiz_cards(session: Session, deck_id: int, mode: str) -> list[Card]:
    cards = list(session.scalars(select(Card).where(Card.deck_id == deck_id).order_by(Card.id)))
    if mode == "typed":
        short = [card for card in cards if len(card.back.split()) <= TYPED_MAX_WORDS]
        cards = short or cards
    return cards


def next_question(session: Session, deck_id: int, mode: str,
                  previous: int | None) -> tuple[Card | None, MCQuestion | None]:
    """The card asked least often so far (never the one just asked, if there is a choice)."""
    cards = _quiz_cards(session, deck_id, mode)
    counts = dict(session.execute(
        select(QuizAttempt.card_id, func.count()).where(QuizAttempt.deck_id == deck_id)
        .group_by(QuizAttempt.card_id)).all())
    candidates = [card for card in cards if card.id != previous] or cards
    candidates.sort(key=lambda card: (counts.get(card.id, 0), card.id))
    if mode != "mc":
        return (candidates[0] if candidates else None), None

    pool = [QuizCard(card.id, card.kind, card.front, card.back)
            for card in session.scalars(select(Card).where(Card.deck_id == deck_id))]
    by_id = {quiz_card.card_id: quiz_card for quiz_card in pool}
    for card in candidates:
        seed = card.id * 7919 + counts.get(card.id, 0)
        question = build_question(by_id[card.id], pool, seed)
        if question is not None:
            return card, question
    return None, None


def question_context(session: Session, deck: Deck, mode: str, number: int, right: int,
                     previous: int | None) -> dict:
    card, question = next_question(session, deck.id, mode, previous)
    return {"deck": deck, "mode": mode, "mode_label": QUIZ_MODES[mode], "card": card,
            "question": question, "number": number, "right": right, "modes": QUIZ_MODES}


def _mode(value: str) -> str:
    return value if value in QUIZ_MODES else "mc"


@router.get("/decks/{deck_id}/quiz")
def quiz_page(request: Request, deck_id: int, mode: str = "mc", session: Session = Depends(get_session)):
    deck = get_or_404(session, Deck, deck_id)
    return render(request, "quiz.html", focus=True, leave_url=f"/decks/{deck.id}",
                  **question_context(session, deck, _mode(mode), 1, 0, None))


@router.get("/quiz/question")
def quiz_question(request: Request, deck: int, mode: str = "mc", number: int = 1, right: int = 0,
                  previous: int | None = None, session: Session = Depends(get_session)):
    deck_row = get_or_404(session, Deck, deck)
    return render(request, "_quiz_question.html",
                  **question_context(session, deck_row, _mode(mode), number, right, previous))


def feedback_context(session: Session, card: Card, attempt: QuizAttempt, mode: str, answer: str,
                     number: int, right: int) -> dict:
    check = check_answer(answer, card.back) if mode == "typed" else None
    return {"deck": get_or_404(session, Deck, card.deck_id), "card": card, "attempt": attempt,
            "mode": mode, "mode_label": QUIZ_MODES[mode], "answer": answer, "check": check,
            "number": number, "right": right, "threshold": CLOSE_THRESHOLD}


@router.post("/quiz/answer")
def quiz_answer(request: Request, card_id: int = Form(...), mode: str = Form("mc"), answer: str = Form(""),
                number: int = Form(1), right: int = Form(0), session: Session = Depends(get_session),
                now: datetime = Depends(current_time)):
    card = get_or_404(session, Card, card_id)
    mode = _mode(mode)
    if mode == "typed":
        check = check_answer(answer, card.back)
        correct, similarity = check.correct, check.similarity
    else:
        correct, similarity = normalise_answer(answer) == normalise_answer(card.back), None
    attempt = services.record_quiz_attempt(session, card, mode, correct, similarity, now)
    session.commit()
    return render(request, "_quiz_feedback.html",
                  **feedback_context(session, card, attempt, mode, answer, number, right + int(correct)))


@router.post("/quiz/attempts/{attempt_id}/override")
def quiz_override(request: Request, attempt_id: int, answer: str = Form(""), number: int = Form(1),
                  right: int = Form(0), session: Session = Depends(get_session)):
    """The learner overrules the similarity check: "I was right" or "I was wrong"."""
    attempt = get_or_404(session, QuizAttempt, attempt_id)
    card = get_or_404(session, Card, attempt.card_id or 0)
    attempt.correct = not attempt.correct
    attempt.overridden = not attempt.overridden
    session.commit()
    right = max(0, right + (1 if attempt.correct else -1))
    return render(request, "_quiz_feedback.html",
                  **feedback_context(session, card, attempt, attempt.mode, answer, number, right))
