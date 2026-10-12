"""Pydantic models passed between the layers."""

from typing import Literal

from pydantic import BaseModel, Field

CardKind = Literal["cloze", "definition", "qa"]
CardOrigin = Literal["offline", "llm", "mock"]


class CardDraft(BaseModel):
    """A proposed card. It becomes a stored card only after the grounding validator accepts it."""

    kind: CardKind
    front: str = Field(min_length=1)
    back: str = Field(min_length=1)
    quote: str
    passage_ordinal: int
    tags: list[str] = Field(default_factory=list)


class Rejection(BaseModel):
    """A proposed card (or a whole model reply) that was turned down, with the reason."""

    reason: str
    passage_ordinal: int
    front: str | None = None
    back: str | None = None
    quote: str | None = None
    detail: str | None = None
