"""The full path: notes -> passages -> drafts -> grounding validator -> stored cards and report."""

import asyncio
import json

import pytest
from sqlalchemy import select

from app import services
from app.config import Settings
from app.errors import IngestionError, LLMAuthError
from app.grounding import check_quote
from app.ingestion.extract import from_pasted
from app.llm.mock import MockProvider
from app.services import CardEditError
from app.storage.models import Card, Deck, GenerationRun, Review, Source
from tests.conftest import NOW, TODAY

SETTINGS = Settings(_env_file=None, llm_provider="mock", llm_max_passages_per_run=3,
                    llm_cards_per_passage=2)

NOTES = """# Devices

A router is a device that forwards packets between different networks. It reads the destination address in every packet it receives and picks the next hop from its routing table. Home routers usually join a small local network to the network of an internet provider.

A switch is a device that forwards frames inside one local network. It learns which MAC address is reachable through each of its ports by watching the traffic. Unlike a hub, it sends each frame only to the port where the destination is connected.

# Addresses

An IP address is a number that identifies a host on a network. An IPv4 address is 32 bits long and an IPv6 address is 128 bits long, which is a far larger space.
"""


def make_source(session, text=NOTES):
    deck = services.create_deck(session, "Networking", "", NOW)
    return services.import_source(session, deck, from_pasted(text), "Test notes", None, NOW)


def run_llm(session, source, provider, settings=SETTINGS):
    return asyncio.run(services.generate_llm_cards(session, source, provider, settings, NOW))


def test_import_stores_passages_with_positions(session):
    source = make_source(session)
    assert [p.section_title for p in source.passages] == ["Devices", "Devices", "Addresses"]
    for row in source.passages:
        assert source.text[row.start_char:row.end_char] == row.text
    assert source.kind == "paste" and source.title == "Test notes"


def test_import_of_only_headings_is_refused(session):
    deck = services.create_deck(session, "Empty", "", NOW)
    with pytest.raises(IngestionError):
        services.import_source(session, deck, from_pasted("# Just a heading"), "x", None, NOW)


def test_offline_generation_stores_grounded_cards_due_today(session):
    source = make_source(session)
    run = services.generate_offline_cards(session, source, NOW)
    cards = source.deck.cards
    assert run.mode == "offline" and run.accepted == len(cards) > 0 and run.rejected == 0
    assert run.passages_used == run.passages_total == 3
    for card in cards:
        assert card.origin == "offline" and card.due_date == TODAY and card.is_new
        assert card.source_passage[card.quote_start:card.quote_end] == card.supporting_quote
        assert check_quote(card.supporting_quote, card.source_passage).ok
        assert card.passage_before + card.supporting_quote + card.passage_after == card.source_passage
        assert card.source_title == "Test notes" and card.section_title in {"Devices", "Addresses"}
        assert card.tag_names in (["devices"], ["addresses"])
    assert {c.front for c in cards} >= {"What is a router?", "What is a switch?", "What is an IP address?"}


def test_running_offline_generation_twice_adds_nothing_and_reports_duplicates(session):
    source = make_source(session)
    first = services.generate_offline_cards(session, source, NOW)
    second = services.generate_offline_cards(session, source, NOW)
    assert second.accepted == 0 and second.rejected == first.accepted
    assert {r.reason for r in second.rejections} == {"duplicate"}
    assert len(source.deck.cards) == first.accepted


def test_llm_good_cards_are_stored_with_the_passages_own_text_as_quote(session):
    source = make_source(session)
    run = run_llm(session, source, MockProvider(mode="good"))
    assert (run.mode, run.provider, run.model) == ("llm", "mock", "mock-model")
    assert run.accepted == 6 and run.rejected == 0 and run.proposed == 6
    for card in source.deck.cards:
        assert card.origin == "mock" and card.kind == "qa"
        assert card.source_passage[card.quote_start:card.quote_end] == card.supporting_quote


def test_llm_cards_with_fake_quotes_are_all_rejected_and_reported(session):
    source = make_source(session)
    run = run_llm(session, source, MockProvider(mode="fake_quotes"))
    assert run.accepted == 0 and run.rejected == 6
    assert source.deck.cards == []
    assert {r.reason for r in run.rejections} == {"quote_not_found"}
    rejected = run.rejections[0]
    assert rejected.front.startswith("Mock question") and rejected.quote and rejected.section_title == "Devices"


def test_llm_mixed_run_keeps_the_real_and_rejects_the_fake(session):
    source = make_source(session)
    run = run_llm(session, source, MockProvider(mode="mixed"))
    assert (run.accepted, run.rejected, run.proposed) == (3, 3, 6)
    assert len(source.deck.cards) == 3
    stored = session.scalars(select(Card)).all()
    assert all(check_quote(card.supporting_quote, card.source_passage).ok for card in stored)


def test_llm_invalid_json_is_reported_per_passage_and_adds_no_cards(session):
    source = make_source(session)
    run = run_llm(session, source, MockProvider(mode="invalid_json"))
    assert run.accepted == 0 and source.deck.cards == []
    assert [(r.reason, r.passage_ordinal) for r in run.rejections] == [
        ("invalid_json", 0), ("invalid_json", 1), ("invalid_json", 2)]


def test_a_quote_from_another_passage_is_rejected(session):
    source = make_source(session)
    wrong_place = json.dumps({"cards": [{
        "question": "How long is an IPv4 address?", "answer": "32 bits",
        "quote": "An IPv4 address is 32 bits long",  # real text, but from passage 2, not passage 0
    }]})
    empty = json.dumps({"cards": []})
    run = run_llm(session, source, MockProvider(responses=[wrong_place, empty, empty]),
                  SETTINGS.model_copy(update={"llm_cards_per_passage": 1}))
    assert run.accepted == 0
    assert [(r.reason, r.passage_ordinal) for r in run.rejections] == [("quote_not_found", 0)]


def test_llm_run_respects_the_passage_limit_and_continues_next_time(session):
    source = make_source(session)
    limited = SETTINGS.model_copy(update={"llm_max_passages_per_run": 2})
    provider = MockProvider(mode="good")
    first = run_llm(session, source, provider, limited)
    assert (first.passages_used, first.passages_total) == (2, 3)
    assert len(provider.calls) == 2  # only these two passages were handed to the provider
    assert all("IPv4" not in call.user for call in provider.calls)

    second = run_llm(session, source, provider, limited)
    assert second.passages_used == 1 and "IPv4" in provider.calls[-1].user


def test_a_wrong_key_stops_the_run_and_stores_nothing(session):
    source = make_source(session)
    session.commit()
    with pytest.raises(LLMAuthError):
        run_llm(session, source, MockProvider(fail_with=LLMAuthError("HTTP 401")))
    session.rollback()
    assert session.scalars(select(Card)).all() == [] and session.scalars(select(GenerationRun)).all() == []


def test_editing_a_card_revalidates_the_quote(session):
    source = make_source(session)
    services.generate_offline_cards(session, source, NOW)
    card = next(c for c in source.deck.cards if c.front == "What is a router?")

    services.update_card(session, card, "What does a router do?", "Forwards packets",
                         "forwards packets between different networks", "week 1, Devices", NOW)
    assert card.front == "What does a router do?" and card.back == "Forwards packets"
    assert card.supporting_quote == "forwards packets between different networks"
    assert card.source_passage[card.quote_start:card.quote_end] == card.supporting_quote
    assert sorted(card.tag_names) == ["devices", "week-1"]

    with pytest.raises(CardEditError, match="does not appear"):
        services.update_card(session, card, "Q?", "A", "a router forwards frames between networks", "", NOW)
    with pytest.raises(CardEditError, match="question and an answer"):
        services.update_card(session, card, "  ", "A", card.supporting_quote, "", NOW)
    with pytest.raises(CardEditError, match="already asks"):
        services.update_card(session, card, "what is a switch", "A", card.supporting_quote, "", NOW)
    assert card.front == "What does a router do?"  # failed edits change nothing


def test_clean_tags():
    assert services.clean_tags("Week 1, exam ,TCP/IP,exam") == ["week-1", "exam", "tcp/ip"]  # commas
    assert services.clean_tags("ports  Exam") == ["ports", "exam"]                           # spaces
    assert services.clean_tags(["Two Words", " x "]) == ["two-words", "x"]
    assert services.clean_tags("") == []


def test_sample_deck_loads_once_and_every_card_is_grounded(session, sample_deck):
    again = services.load_sample_deck(session, NOW)
    assert again.id == sample_deck.id and len(session.scalars(select(Deck)).all()) == 1
    assert len(sample_deck.cards) >= 20
    assert all(check_quote(c.supporting_quote, c.source_passage).ok for c in sample_deck.cards)


def test_deleting_a_source_keeps_its_cards_checkable(session):
    source = make_source(session)
    services.generate_offline_cards(session, source, NOW)
    session.commit()
    deck_id = source.deck_id
    session.delete(source)
    session.commit()
    cards = session.scalars(select(Card).where(Card.deck_id == deck_id)).all()
    assert cards and all(card.passage_id is None for card in cards)
    assert all(check_quote(card.supporting_quote, card.source_passage).ok for card in cards)


def test_deleting_a_deck_removes_its_cards_sources_and_history(session):
    source = make_source(session)
    services.generate_offline_cards(session, source, NOW)
    services.rate_card(session, source.deck.cards[0], 3, NOW)
    session.commit()
    session.delete(source.deck)
    session.commit()
    for model in (Deck, Source, Card, Review, GenerationRun):
        assert session.scalars(select(model)).all() == []
