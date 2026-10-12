"""LLM card generation: one request per passage, replies parsed and validated as JSON.

This module only turns model output into card drafts and reports what was unusable. Whether a
draft's quote is real is decided afterwards by the grounding validator, the same one offline
cards go through.
"""

import asyncio
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.errors import LLMAuthError, LLMError, MalformedOutputError
from app.generation.offline import section_tag
from app.generation.prompts import build_prompts
from app.ingestion.splitter import Passage
from app.llm.base import LLMProvider, LLMRequest
from app.llm.structured import extract_json_object
from app.schemas import CardDraft, Rejection

JSON_RETRIES = 1
DEFAULT_CONCURRENCY = 2


class LLMCard(BaseModel):
    """One card as the model must return it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=3, max_length=400)
    answer: str = Field(min_length=1, max_length=600)
    quote: str = Field(min_length=1, max_length=2000)


@dataclass
class LLMGenerationResult:
    drafts: list[CardDraft] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    passages_sent: int = 0


def _short(value: object, limit: int = 300) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    return text[:limit]


async def _cards_json(provider: LLMProvider, request: LLMRequest) -> list:
    """The `cards` list from the model's reply. One retry if the reply is not usable JSON."""
    last_error: MalformedOutputError | None = None
    for _attempt in range(1 + JSON_RETRIES):
        response = await provider.complete(request)
        try:
            cards = extract_json_object(response.text).get("cards")
            if not isinstance(cards, list):
                raise MalformedOutputError('the JSON object has no "cards" list')
            return cards
        except MalformedOutputError as exc:
            last_error = exc
    raise last_error  # type: ignore[misc]


async def generate_for_passage(provider: LLMProvider, passage: Passage,
                               max_cards: int) -> tuple[list[CardDraft], list[Rejection]]:
    system, user = build_prompts(passage.text, passage.section_title, max_cards)
    request = LLMRequest(system=system, user=user,
                         metadata={"passage": passage.text, "max_cards": max_cards})
    try:
        items = await _cards_json(provider, request)
    except LLMAuthError:
        raise  # a wrong key fails every passage; stop the run and say so
    except MalformedOutputError as exc:
        return [], [Rejection(reason="invalid_json", passage_ordinal=passage.ordinal, detail=str(exc))]
    except LLMError as exc:
        return [], [Rejection(reason="provider_error", passage_ordinal=passage.ordinal, detail=str(exc))]

    drafts: list[CardDraft] = []
    rejections: list[Rejection] = []
    for item in items[:max_cards]:
        try:
            card = LLMCard.model_validate(item)
        except ValidationError as exc:
            raw = item if isinstance(item, dict) else {}
            fields = ", ".join(sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]}))
            rejections.append(Rejection(
                reason="invalid_schema", passage_ordinal=passage.ordinal,
                front=_short(raw.get("question")), back=_short(raw.get("answer")),
                quote=_short(raw.get("quote")), detail=f"problem with: {fields or 'the card object'}",
            ))
            continue
        drafts.append(CardDraft(kind="qa", front=card.question, back=card.answer, quote=card.quote,
                                passage_ordinal=passage.ordinal, tags=section_tag(passage.section_title)))
    return drafts, rejections


async def generate_llm(provider: LLMProvider, passages: list[Passage], max_cards: int = 3,
                       concurrency: int = DEFAULT_CONCURRENCY) -> LLMGenerationResult:
    """Ask the provider for cards for each passage, a few at a time, keeping passage order."""
    gate = asyncio.Semaphore(max(1, concurrency))

    async def one(passage: Passage):
        async with gate:
            return await generate_for_passage(provider, passage, max_cards)

    result = LLMGenerationResult(passages_sent=len(passages))
    for drafts, rejections in await asyncio.gather(*(one(p) for p in passages)):
        result.drafts.extend(drafts)
        result.rejections.extend(rejections)
    return result
