import pytest

from app.quiz.similarity import CLOSE_THRESHOLD, check_answer, normalise_answer


@pytest.mark.parametrize("raw, expected", [
    ("  The Default   Gateway. ", "default gateway"),
    ("A router", "router"),
    ("an IP address", "ip address"),
    ("Round-trip time", "round trip time"),
    ("65,535", "65535"),
    ("192.168.1.20", "192.168.1.20"),
    ("Théâtre", "théâtre"),
    ("the", "the"),  # an article on its own is the answer, not a prefix
])
def test_normalise_answer(raw, expected):
    assert normalise_answer(raw) == expected


def test_exact_after_normalisation():
    check = check_answer("the default gateway", "Default gateway")
    assert (check.verdict, check.similarity, check.correct) == ("exact", 1.0, True)


@pytest.mark.parametrize("typed, expected", [
    ("encapsulaton", "Encapsulation"),          # one letter missing
    ("routers", "router"),                      # plural
    ("transmision control protocol", "Transmission Control Protocol"),
])
def test_small_slips_are_close_enough(typed, expected):
    check = check_answer(typed, expected)
    assert check.verdict == "close" and check.correct
    assert CLOSE_THRESHOLD <= check.similarity < 1.0


@pytest.mark.parametrize("typed, expected", [
    ("switch", "router"),
    ("UDP", "TCP"),
    ("", "router"),
    ("   ", "router"),
    ("user datagram protocol", "Transmission Control Protocol"),
])
def test_wrong_answers_are_wrong(typed, expected):
    check = check_answer(typed, expected)
    assert check.verdict == "wrong" and not check.correct
    assert check.similarity < CLOSE_THRESHOLD


def test_answers_with_digits_must_match_exactly():
    near = check_answer("192.168.1.21", "192.168.1.20")
    assert near.similarity >= CLOSE_THRESHOLD  # it looks close, which is exactly the danger
    assert near.verdict == "wrong"
    assert check_answer("65535", "65,535").verdict == "exact"
    assert check_answer("33", "32").verdict == "wrong"


def test_the_check_reports_what_it_compared():
    check = check_answer("  Routers ", "A router")
    assert (check.typed, check.expected) == ("routers", "router")
