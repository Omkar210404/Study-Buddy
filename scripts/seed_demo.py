"""Build a demo database with SIMULATED review history, for screenshots and trying the app.

A fresh install has no history, so the progress page is empty. This script loads the bundled
sample notes into a separate database file and then replays two weeks of study, day by day,
through the app's real code (the same queue and SM-2 functions the review screen uses). The
ratings themselves are drawn from a fixed-seed random generator: they are made up, not the
record of a real learner. Never present numbers from this database as real results.

Usage:
    python scripts/seed_demo.py                 # writes data/demo.db
    python scripts/seed_demo.py --db other.db --days 14 --seed 7
Then start the app on it:
    DATABASE_PATH=data/demo.db uvicorn app.main:app      (PowerShell: $env:DATABASE_PATH="data/demo.db")
"""

import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app import services  # noqa: E402
from app.scheduler.queue import build_queue  # noqa: E402
from app.scheduler.sm2 import AGAIN, EASY, GOOD, HARD  # noqa: E402
from app.storage.db import init_db, make_engine, make_session_factory  # noqa: E402
from app.storage.models import Card, Review  # noqa: E402

DEMO_DECK_NAME = "Networking basics (simulated history)"
NEW_PER_DAY = 8
REST_DAYS = {5, 10}   # days with no study, counted from the first simulated day
QUIZ_DAYS = {3, 8, 12}
FIRST_LOOK_WEIGHTS = {AGAIN: 15, HARD: 20, GOOD: 50, EASY: 15}
REVIEW_WEIGHTS = {AGAIN: 12, HARD: 18, GOOD: 55, EASY: 15}


def simulate(db_path: Path, days: int, seed: int) -> None:
    rng = random.Random(seed)
    engine = make_engine(db_path)
    init_db(engine)
    first_day = datetime.now().replace(hour=19, minute=0, second=0, microsecond=0) - timedelta(days=days)

    with make_session_factory(engine)() as session:
        deck = services.load_sample_deck(session, first_day)
        # The name says it on every screen, so a screenshot cannot pass this off as real study.
        deck.name = DEMO_DECK_NAME
        deck.description = "Sample notes written for this project. The review history here was simulated by scripts/seed_demo.py."
        session.commit()

        for offset in range(days):  # up to yesterday: today's queue is left for the demo
            if offset in REST_DAYS:
                continue
            now = first_day + timedelta(days=offset)
            for _ in range(500):  # each pass rates the card at the front of the queue
                queue = build_queue(session, now.date(), NEW_PER_DAY, deck.id)
                if not queue:
                    break
                card = queue[0]
                if card.due_date > now.date():
                    rating = GOOD  # a same-day repeat after Again
                else:
                    weights = FIRST_LOOK_WEIGHTS if card.is_new else REVIEW_WEIGHTS
                    rating = rng.choices(list(weights), weights=list(weights.values()))[0]
                now += timedelta(seconds=rng.randint(8, 40))
                services.rate_card(session, card, rating, now)
            if offset in QUIZ_DAYS:
                seen = list(session.scalars(select(Card).where(Card.last_reviewed_at.is_not(None))))
                for card in rng.sample(seen, min(6, len(seen))):
                    services.record_quiz_attempt(session, card, "mc", rng.random() < 0.8, None, now)
            session.commit()

        total = session.scalar(select(func.count()).select_from(Review))
        per_day = session.execute(
            select(Review.review_date, func.count()).group_by(Review.review_date).order_by(Review.review_date)
        ).all()
        print(f"Wrote {db_path} with {len(deck.cards)} cards and {total} SIMULATED reviews (seed {seed}).")
        for day, count in per_day:
            print(f"  {day}  {count}")
    engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", type=Path, default=Path("data/demo.db"))
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--overwrite", action="store_true", help="replace the file if it exists")
    args = parser.parse_args()

    if args.db.exists():
        if not args.overwrite:
            sys.exit(f"{args.db} already exists. Pass --overwrite to replace it.")
        args.db.unlink()
    simulate(args.db, args.days, args.seed)


if __name__ == "__main__":
    main()
