import pytest

from app.grounding import REASONS, check_quote, question_key
from app.grounding.normalise import normalise, normalise_with_map

PASSAGE = (
    "**TCP** is a connection-oriented protocol.  It sets up a connection\n"
    "with a three-way handshake before any data is sent. The sender’s window\n"
    "limits how much unacknowledged data is “in flight” – this is flow control."
)


def test_accepts_an_exact_quote_and_returns_its_position():
    quote = "It sets up a connection"
    result = check_quote(quote, PASSAGE)
    assert result.ok and result.reason is None
    assert result.quote == quote
    assert PASSAGE[result.start:result.end] == quote


def test_accepts_whitespace_differences():
    result = check_quote("It sets up a connection with a   three-way handshake", PASSAGE)
    assert result.ok
    # What is stored is the passage's own text, line break included, not the submitted wording.
    assert result.quote == "It sets up a connection\nwith a three-way handshake"
    assert PASSAGE[result.start:result.end] == result.quote


def test_accepts_straight_quotes_and_hyphen_for_typographic_ones():
    result = check_quote("The sender's window limits how much unacknowledged data is \"in flight\" - this", PASSAGE)
    assert result.ok
    assert result.quote.startswith("The sender’s window") and "“in flight” –" in result.quote


def test_markdown_markers_are_ignored_and_kept_balanced():
    result = check_quote("TCP is a connection-oriented protocol.", PASSAGE)
    assert result.ok
    assert result.quote == "**TCP** is a connection-oriented protocol."
    code = "Run the `ping` command to test reachability."
    assert check_quote("Run the ping command", code).quote == "Run the `ping` command"


def test_accepts_a_quote_the_model_wrapped_in_quotation_marks():
    assert check_quote('"with a three-way handshake before any data is sent"', PASSAGE).ok


@pytest.mark.parametrize("fake", [
    "TCP is a connectionless protocol.",                      # one word changed
    "UDP sets up a connection with a three-way handshake",    # invented subject
    "It sets up a connection ... before any data is sent.",   # elided in the middle
    "it sets up a connection with a three-way handshake",     # letter case changed
    "This sentence is not in the notes at all.",
])
def test_rejects_quotes_that_are_not_in_the_passage(fake):
    result = check_quote(fake, PASSAGE)
    assert not result.ok
    assert result.reason == "quote_not_found"
    assert result.quote is None and result.start is None
    assert result.message == REASONS["quote_not_found"]


def test_rejects_a_quote_from_a_different_passage():
    other = "UDP sends datagrams without setting up a connection first."
    assert check_quote("UDP sends datagrams without setting up a connection", other).ok
    assert check_quote("UDP sends datagrams without setting up a connection", PASSAGE).reason == "quote_not_found"


@pytest.mark.parametrize("quote, reason", [
    (None, "quote_missing"),
    ("", "quote_missing"),
    ("   \n ", "quote_missing"),
    ("TCP", "quote_too_short"),
    ("is a", "quote_too_short"),
    ("connection-oriented protocol", "quote_too_short"),  # long enough in characters, only 2 words
])
def test_rejects_missing_and_trivial_quotes(quote, reason):
    assert check_quote(quote, PASSAGE).reason == reason


def test_rejects_a_quote_that_is_too_long():
    long_passage = "Packets are forwarded hop by hop until they arrive. " * 10
    assert check_quote(long_passage, long_passage).reason == "quote_too_long"


def test_normalise_map_points_back_into_the_original():
    text = "  ﬁrst\t\tline\n\nsecond “line”  "
    normalised, index_map = normalise_with_map(text)
    assert normalised == 'first line second "line"'
    assert len(normalised) == len(index_map)
    assert text[index_map[0]] == "ﬁ" and text[index_map[-1]] == "”"


def test_normalise_keeps_case_and_words():
    assert normalise("TCP  is\nReliable") == "TCP is Reliable"
    assert normalise("a * b") == "a * b"  # a lone asterisk is content, not a marker


def test_question_key_ignores_case_spacing_and_final_punctuation():
    assert question_key("What is  TCP?") == question_key("what is tcp")
    assert question_key("What is TCP?") != question_key("What is UDP?")
