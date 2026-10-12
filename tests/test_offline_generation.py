from pathlib import Path

import pytest

from app.generation.offline import BLANK, find_definition, generate_offline, make_cloze, section_tag
from app.generation.terms import score_terms
from app.grounding import check_quote
from app.ingestion.extract import from_file
from app.ingestion.splitter import Passage, split_passages

SAMPLE = Path(__file__).resolve().parents[1] / "sample_notes" / "networking-basics.md"


def passage(text, ordinal=0, title=None):
    return Passage(ordinal=ordinal, section_title=title, text=text, start_char=0, end_char=len(text))


def sample_passages():
    extracted = from_file(SAMPLE.name, SAMPLE.read_bytes(), 5 * 1024 * 1024)
    return split_passages(extracted.text)


# --- definition cards -------------------------------------------------------------------------

@pytest.mark.parametrize("sentence, front, back", [
    ("A router is a device that forwards packets between networks.",
     "What is a router?", "A device that forwards packets between networks"),
    ("The transport layer is the layer that delivers data to applications.",
     "What is the transport layer?", "The layer that delivers data to applications"),
    ("Checksums are a way of detecting damaged data.",
     "What are Checksums?", "A way of detecting damaged data"),
    ("Encapsulation refers to wrapping data inside a header.",
     "What does Encapsulation refer to?", "Wrapping data inside a header"),
    ("Throughput is defined as the amount of data delivered per second.",
     "How is Throughput defined?", "The amount of data delivered per second"),
    ("Bandwidth means the amount of data a link can carry.",
     "What does Bandwidth mean?", "The amount of data a link can carry"),
    ("TCP stands for Transmission Control Protocol.",
     "What does TCP stand for?", "Transmission Control Protocol"),
    ("The time for a message to go there and back is called the round-trip time.",
     "What do we call the time for a message to go there and back?", "Round-trip time"),
    ("A network that covers one building is known as a local area network.",
     "What do we call a network that covers one building?", "Local area network"),
    ("In networking, a protocol is a set of rules for exchanging data.",
     "What is a protocol?", "A set of rules for exchanging data"),
])
def test_definition_patterns(sentence, front, back):
    assert find_definition(sentence) == (front, back)


@pytest.mark.parametrize("sentence", [
    "It is a device that forwards packets between networks.",      # pronoun subject
    "This is the reason that routers keep a routing table.",       # pronoun subject
    "The link layer moves frames between devices on one network.",  # no defining verb
    "Routers are fast.",                                            # too short to define anything
    "A resolver looks up the answer, which is known as caching.",   # "known as" names the clause, not a term
])
def test_sentences_that_are_not_definitions(sentence):
    assert find_definition(sentence) is None


def test_glossary_lines_only_count_in_lists_or_after_a_bold_term():
    line = "Switch: a device that forwards frames inside one network."
    assert find_definition(line) is None
    assert find_definition(line, glossary_line=True) == (
        "Define: Switch", "A device that forwards frames inside one network")
    assert find_definition("Note: this section is only a short summary of it.", glossary_line=True) is None


def test_definition_keeps_only_the_clause_before_a_colon():
    front, back = find_definition(
        "TCP is a connection-oriented protocol: the hosts set up a connection before sending data.")
    assert (front, back) == ("What is TCP?", "A connection-oriented protocol")


def test_sentence_initial_capital_is_undone_when_the_notes_use_lower_case():
    sentence = "Latency refers to the delay before data arrives."
    assert find_definition(sentence, lower_words=frozenset({"latency"}))[0] == "What does latency refer to?"
    assert find_definition(sentence)[0] == "What does Latency refer to?"


# --- cloze cards ------------------------------------------------------------------------------

def test_make_cloze_blanks_every_occurrence_as_a_whole_word():
    front = make_cloze("UDP is light because UDP sends no acknowledgements at all.", "UDP")
    assert front == f"{BLANK} is light because {BLANK} sends no acknowledgements at all."
    assert make_cloze("A port is not the same thing as a passport.", "port").count(BLANK) == 1
    assert make_cloze("Routers forward packets.", "packets") is None  # too little left to answer from


def test_term_scores_reward_repetition_emphasis_and_acronyms():
    passages = [
        "A **checksum** detects damaged data. The receiver recomputes the checksum.",
        "The sender adds a header. DNS answers arrive quickly.",
        "A table lists every known route.",
    ]
    scores = score_terms(passages, headings=[])
    assert scores["checksum"] > scores["header"]   # bold and repeated beats a word seen once
    assert scores["dns"] > scores["sender"]        # an acronym beats a plain word seen once
    assert "the" not in scores and "a" not in scores


def test_cloze_blanks_a_key_term_and_quotes_the_whole_sentence():
    text = (
        "The **handshake** opens a connection between two hosts on the network. "
        "After the handshake both hosts can send data in either direction."
    )
    drafts = generate_offline([passage(text)])
    assert drafts and all(d.kind == "cloze" for d in drafts)
    first = drafts[0]
    assert first.back == "handshake" and BLANK in first.front and "handshake" not in first.front
    assert first.quote == "The **handshake** opens a connection between two hosts on the network."
    assert "**" not in first.front  # card text is clean; the quote stays verbatim


def test_numbers_are_preferred_blanks():
    text = "Because the field is short, an IPv4 address is only 32 bits long in every packet."
    drafts = generate_offline([passage(text)])
    assert [(d.back, d.kind) for d in drafts] == [("32", "cloze")]


def test_questions_and_fragments_are_skipped():
    assert generate_offline([passage("What is a router? Too short. See also page 3.")]) == []


# --- whole-source behaviour -------------------------------------------------------------------

def test_generation_is_deterministic():
    passages = sample_passages()
    assert generate_offline(passages) == generate_offline(passages)


def test_every_card_from_the_sample_notes_is_grounded():
    passages = sample_passages()
    drafts = generate_offline(passages)
    assert len(drafts) >= 20
    for draft in drafts:
        source = passages[draft.passage_ordinal].text
        result = check_quote(draft.quote, source)
        assert result.ok, (draft.front, result.reason)
        assert result.quote == draft.quote  # verbatim, so nothing changes on the way in


def test_sample_notes_produce_both_kinds_without_duplicate_questions():
    drafts = generate_offline(sample_passages())
    kinds = {d.kind for d in drafts}
    assert kinds == {"definition", "cloze"}
    fronts = [d.front.lower() for d in drafts]
    assert len(fronts) == len(set(fronts))
    by_front = {d.front: d.back for d in drafts}
    assert by_front["What does TCP stand for?"] == "Transmission Control Protocol"
    assert by_front["What is a subnet mask?"].startswith("A value that separates")


def test_cards_per_passage_are_capped():
    passages = sample_passages()
    drafts = generate_offline(passages)
    for p in passages:
        mine = [d for d in drafts if d.passage_ordinal == p.ordinal]
        assert len(mine) <= 5
        assert sum(d.kind == "cloze" for d in mine) <= 3


def test_cards_are_tagged_with_their_section():
    drafts = generate_offline(sample_passages())
    assert {"tcp-and-udp", "addresses", "ports"} <= {tag for d in drafts for tag in d.tags}
    assert section_tag("The TCP/IP model") == ["the-tcp-ip-model"]
    assert section_tag(None) == []
