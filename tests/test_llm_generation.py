"""LLM-mode generation, exercised end to end with the mock provider. No key, no network."""

import asyncio
import json

import pytest

from app.errors import LLMAuthError, LLMProviderError
from app.generation.llm import generate_for_passage, generate_llm
from app.grounding import check_quote
from app.ingestion.splitter import Passage
from app.llm.mock import INVENTED_QUOTE, NOT_JSON_REPLY, MockProvider

TEXT = (
    "A router is a device that forwards packets between different networks. "
    "It reads the destination address in every packet it receives. "
    "The routing table tells the router which neighbour is closer to the destination. "
    "Short one."
)
PASSAGE = Passage(ordinal=4, section_title="Devices", text=TEXT, start_char=0, end_char=len(TEXT))
OTHER_TEXT = "A switch is a device that forwards frames inside one local network using MAC addresses."
OTHER = Passage(ordinal=5, section_title="Devices", text=OTHER_TEXT, start_char=0, end_char=len(OTHER_TEXT))


def run(coroutine):
    return asyncio.run(coroutine)


def reply(*cards) -> str:
    return json.dumps({"cards": list(cards)})


GOOD_CARD = {"question": "What does a router do?", "answer": "It forwards packets between networks.",
             "quote": "A router is a device that forwards packets between different networks."}


def test_good_mode_gives_cards_whose_quotes_are_in_the_passage():
    provider = MockProvider(mode="good")
    drafts, rejections = run(generate_for_passage(provider, PASSAGE, max_cards=3))
    assert len(drafts) == 3 and rejections == []
    for draft in drafts:
        assert draft.kind == "qa" and draft.passage_ordinal == 4 and draft.tags == ["devices"]
        assert check_quote(draft.quote, TEXT).ok


def test_fake_quotes_mode_gives_cards_the_grounding_check_rejects():
    provider = MockProvider(mode="fake_quotes")
    drafts, rejections = run(generate_for_passage(provider, PASSAGE, max_cards=3))
    assert len(drafts) == 3 and rejections == []  # the JSON is fine; the quotes are not
    assert drafts[0].quote == INVENTED_QUOTE
    assert drafts[1].quote.endswith("definitely.")  # a real sentence with one word changed
    assert [check_quote(d.quote, TEXT).reason for d in drafts] == ["quote_not_found"] * 3


def test_mixed_mode_alternates_real_and_fake_quotes():
    drafts, _ = run(generate_for_passage(MockProvider(mode="mixed"), PASSAGE, max_cards=3))
    assert [check_quote(d.quote, TEXT).ok for d in drafts] == [True, False, True]


def test_invalid_json_is_retried_once_then_reported():
    provider = MockProvider(mode="invalid_json")
    drafts, rejections = run(generate_for_passage(provider, PASSAGE, max_cards=3))
    assert drafts == []
    assert [(r.reason, r.passage_ordinal) for r in rejections] == [("invalid_json", 4)]
    assert len(provider.calls) == 2


def test_a_good_reply_after_a_bad_one_is_used():
    provider = MockProvider(responses=[NOT_JSON_REPLY, reply(GOOD_CARD)])
    drafts, rejections = run(generate_for_passage(provider, PASSAGE, max_cards=3))
    assert [d.front for d in drafts] == ["What does a router do?"] and rejections == []


def test_fenced_json_with_chatter_is_accepted():
    text = "Here you go:\n```json\n" + reply(GOOD_CARD) + "\n```"
    drafts, rejections = run(generate_for_passage(MockProvider(responses=[text]), PASSAGE, max_cards=3))
    assert len(drafts) == 1 and rejections == []


def test_each_card_is_validated_on_its_own():
    cards = [
        GOOD_CARD,
        {"question": "What is missing here?", "answer": "The quote."},  # no quote
        {"question": "", "answer": "No question.", "quote": "It reads the destination address"},
        "not even an object",
        {"question": " What does it read? ", "answer": " The destination address. ",
         "quote": "It reads the destination address in every packet it receives."},
    ]
    provider = MockProvider(responses=[reply(*cards)])
    drafts, rejections = run(generate_for_passage(provider, PASSAGE, max_cards=5))
    assert [d.front for d in drafts] == ["What does a router do?", "What does it read?"]  # stripped
    assert [r.reason for r in rejections] == ["invalid_schema"] * 3
    assert rejections[0].front == "What is missing here?" and "quote" in rejections[0].detail
    assert len(provider.calls) == 1  # schema problems are reported, not retried


@pytest.mark.parametrize("text", ['{"cards": "none"}', '{"flashcards": []}', "[1, 2, 3]"])
def test_json_without_a_cards_list_counts_as_invalid_json(text):
    provider = MockProvider(responses=[text, text])
    drafts, rejections = run(generate_for_passage(provider, PASSAGE, max_cards=3))
    assert drafts == [] and [r.reason for r in rejections] == ["invalid_json"]


def test_an_empty_cards_list_is_a_valid_answer():
    drafts, rejections = run(generate_for_passage(MockProvider(responses=[reply()]), PASSAGE, max_cards=3))
    assert drafts == [] and rejections == []


def test_extra_cards_beyond_the_limit_are_dropped():
    provider = MockProvider(responses=[reply(GOOD_CARD, GOOD_CARD, GOOD_CARD)])
    drafts, _ = run(generate_for_passage(provider, PASSAGE, max_cards=2))
    assert len(drafts) == 2


def test_provider_failure_is_reported_per_passage():
    provider = MockProvider(fail_with=LLMProviderError("provider returned HTTP 500: boom"))
    result = run(generate_llm(provider, [PASSAGE, OTHER], max_cards=3))
    assert result.drafts == [] and result.passages_sent == 2
    assert [(r.reason, r.passage_ordinal) for r in result.rejections] == [
        ("provider_error", 4), ("provider_error", 5)]
    assert "HTTP 500" in result.rejections[0].detail


def test_a_wrong_key_stops_the_run():
    provider = MockProvider(fail_with=LLMAuthError("provider returned HTTP 401: invalid api key"))
    with pytest.raises(LLMAuthError):
        run(generate_llm(provider, [PASSAGE, OTHER], max_cards=3))


def test_generate_llm_keeps_passage_order_and_sends_one_request_per_passage():
    provider = MockProvider(mode="good")
    result = run(generate_llm(provider, [PASSAGE, OTHER], max_cards=2, concurrency=2))
    assert [d.passage_ordinal for d in result.drafts] == [4, 4, 5]
    assert len(provider.calls) == 2
    request = provider.calls[0]
    assert TEXT in request.user and "Section: Devices" in request.user
    assert "at most 2 cards" in request.system and "character for character" in request.system
