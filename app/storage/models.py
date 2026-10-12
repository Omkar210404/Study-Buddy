"""Database tables (SQLAlchemy 2.0)."""

from datetime import date, datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.scheduler.sm2 import INITIAL_EASE


class Base(DeclarativeBase):
    pass


card_tags = Table(
    "card_tags",
    Base.metadata,
    Column("card_id", ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Deck(Base):
    __tablename__ = "decks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime)

    sources: Mapped[list["Source"]] = relationship(
        back_populates="deck", cascade="all, delete-orphan", passive_deletes=True, order_by="Source.id")
    cards: Mapped[list["Card"]] = relationship(
        back_populates="deck", cascade="all, delete-orphan", passive_deletes=True, order_by="Card.id")


class Source(Base):
    """One imported set of notes. `text` is the canonical text that passage offsets point into."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(10))
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    deck: Mapped[Deck] = relationship(back_populates="sources")
    passages: Mapped[list["PassageRow"]] = relationship(
        back_populates="source", cascade="all, delete-orphan", passive_deletes=True,
        order_by="PassageRow.ordinal")


class PassageRow(Base):
    __tablename__ = "passages"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    section_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    start_char: Mapped[int] = mapped_column(Integer)
    end_char: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source: Mapped[Source] = relationship(back_populates="passages")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)


class Card(Base):
    """A study card. It always carries the passage it came from and a quote found in that passage."""

    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), index=True)
    passage_id: Mapped[int | None] = mapped_column(
        ForeignKey("passages.id", ondelete="SET NULL"), nullable=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(12))
    origin: Mapped[str] = mapped_column(String(10))
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text)

    # Grounding. The passage is kept as a snapshot so the card stays checkable if its source is deleted.
    supporting_quote: Mapped[str] = mapped_column(Text)
    source_passage: Mapped[str] = mapped_column(Text)
    quote_start: Mapped[int] = mapped_column(Integer)
    quote_end: Mapped[int] = mapped_column(Integer)
    section_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_title: Mapped[str] = mapped_column(String(200), default="")

    # SM-2 state
    ease_factor: Mapped[float] = mapped_column(Float, default=INITIAL_EASE)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    deck: Mapped[Deck] = relationship(back_populates="cards")
    tags: Mapped[list[Tag]] = relationship(secondary=card_tags, order_by="Tag.name")

    @property
    def is_new(self) -> bool:
        return self.last_reviewed_at is None

    @property
    def tag_names(self) -> list[str]:
        return [tag.name for tag in self.tags]

    @property
    def passage_before(self) -> str:
        return self.source_passage[:self.quote_start]

    @property
    def passage_after(self) -> str:
        return self.source_passage[self.quote_end:]


class Review(Base):
    """One press of a rating button. `scheduled` is False for same-day repeats after Again."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int | None] = mapped_column(ForeignKey("cards.id", ondelete="SET NULL"), nullable=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), index=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime)
    review_date: Mapped[date] = mapped_column(Date, index=True)
    rating: Mapped[int] = mapped_column(Integer)
    scheduled: Mapped[bool] = mapped_column(Boolean)
    was_new: Mapped[bool] = mapped_column(Boolean)
    ease_before: Mapped[float] = mapped_column(Float)
    ease_after: Mapped[float] = mapped_column(Float)
    interval_before: Mapped[int] = mapped_column(Integer)
    interval_after: Mapped[int] = mapped_column(Integer)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int | None] = mapped_column(ForeignKey("cards.id", ondelete="SET NULL"), nullable=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(10))  # mc | typed
    correct: Mapped[bool] = mapped_column(Boolean)
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    answered_at: Mapped[datetime] = mapped_column(DateTime)


class GenerationRun(Base):
    """One press of "Generate cards": what was proposed, kept and rejected."""

    __tablename__ = "generation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"), nullable=True)
    source_title: Mapped[str] = mapped_column(String(200), default="")
    mode: Mapped[str] = mapped_column(String(10))  # offline | llm
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    passages_total: Mapped[int] = mapped_column(Integer, default=0)
    passages_used: Mapped[int] = mapped_column(Integer, default=0)
    proposed: Mapped[int] = mapped_column(Integer, default=0)
    accepted: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    rejections: Mapped[list["RejectedCard"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="RejectedCard.id")
    cards: Mapped[list[Card]] = relationship(order_by="Card.id", viewonly=True)


class RejectedCard(Base):
    __tablename__ = "rejected_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("generation_runs.id", ondelete="CASCADE"), index=True)
    passage_ordinal: Mapped[int] = mapped_column(Integer)
    section_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reason: Mapped[str] = mapped_column(String(30))
    front: Mapped[str | None] = mapped_column(Text, nullable=True)
    back: Mapped[str | None] = mapped_column(Text, nullable=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
