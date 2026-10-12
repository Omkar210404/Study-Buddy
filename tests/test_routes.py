"""The main routes through FastAPI's TestClient: the app as a learner uses it."""

import csv
import io
import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.storage.models import Card, QuizAttempt, Review
from app.web.app import create_app
from tests.helpers import make_blank_pdf, make_text_pdf

START = datetime(2026, 10, 12, 9, 0)

NOTES = """# Devices

A router is a device that forwards packets between different networks. It reads the destination address in every packet it receives and picks the next hop from its routing table. Home routers usually join a small local network to the network of an internet provider.

A switch is a device that forwards frames inside one local network. It learns which MAC address is reachable through each of its ports by watching the traffic. Unlike a hub, it sends each frame only to the port where the destination is connected.

# Addresses

An IP address is a number that identifies a host on a network. An IPv4 address is 32 bits long and an IPv6 address is 128 bits long, which is a far larger space.
"""


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self) -> datetime:
        return self.now


def make_client(tmp_path, clock, **settings):
    config = Settings(_env_file=None, database_path=tmp_path / "app.db", **settings)
    return TestClient(create_app(config, clock=clock))


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def client(tmp_path, clock):
    """Offline mode, the default."""
    with make_client(tmp_path, clock, llm_provider="none") as test_client:
        yield test_client


@pytest.fixture
def mock_client(tmp_path, clock):
    """LLM mode with the mock provider returning a mix of real and fake quotes."""
    with make_client(tmp_path, clock, llm_provider="mock", mock_llm_mode="mixed",
                     llm_cards_per_passage=2) as test_client:
        yield test_client


def db(client):
    return client.app.state.session_factory()


def new_deck(client, name="Networking") -> str:
    response = client.post("/decks", data={"name": name}, follow_redirects=False)
    assert response.status_code == 303
    return response.headers["location"]


def import_notes(client, deck_url, text=NOTES, title="Lecture notes") -> str:
    response = client.post(f"{deck_url}/sources", data={"title": title, "text": text}, follow_redirects=False)
    assert response.status_code == 303, response.text
    return response.headers["location"]


def deck_with_cards(client) -> str:
    deck_url = new_deck(client)
    source_url = import_notes(client, deck_url)
    assert client.post(f"{source_url}/generate", data={"mode": "offline"}).status_code == 200
    return deck_url


def current_card_id(html: str) -> int:
    return int(re.search(r'hx-post="/review/(\d+)/rate"', html).group(1))


# --- first run ---------------------------------------------------------------------------------

def test_empty_app_offers_the_sample_and_is_healthy(client):
    home = client.get("/")
    assert home.status_code == 200
    assert "Try it with the sample notes" in home.text
    assert "Offline mode. Nothing leaves this computer." in home.text
    assert client.get("/health").json() == {"status": "ok"}
    assert "Nothing to show yet" in client.get("/progress").text


def test_pages_load_no_assets_from_other_hosts(client):
    for path in ("/", "/decks", "/progress", "/privacy"):
        html = client.get(path).text
        assert not re.search(r'(?:src|href)="https?://', html), path
    assert client.get("/static/htmx.min.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_sample_deck_loads_with_cards_and_a_daily_limit(client):
    response = client.post("/demo/load-sample", follow_redirects=False)
    deck_url = response.headers["location"]
    deck = client.get(deck_url)
    assert "Networking basics (sample)" in deck.text
    assert "What does TCP stand for?" in deck.text and "Transmission Control Protocol" in deck.text
    assert "20 due today" in deck.text  # more cards exist, but new cards are capped per day
    assert "<strong>20 cards</strong> due today" in client.get("/").text
    assert client.post("/demo/load-sample", follow_redirects=False).headers["location"] == deck_url


# --- import ------------------------------------------------------------------------------------

def test_paste_import_shows_passages_with_their_positions(client):
    source_url = import_notes(client, new_deck(client))
    page = client.get(source_url)
    assert "3 passages from\n  pasted text" in page.text or "3 passages" in page.text
    assert "Passage 1 · Devices" in page.text and "Passage 3 · Addresses" in page.text
    assert re.search(r"characters \d+–\d+", page.text)
    assert "Generate cards offline" in page.text
    assert "LLM mode is off" in page.text


@pytest.mark.parametrize("filename, content, kind", [
    ("notes.txt", NOTES.encode(), "a text file"),
    ("notes.md", NOTES.encode(), "a Markdown file"),
])
def test_text_file_upload(client, filename, content, kind):
    deck_url = new_deck(client)
    response = client.post(f"{deck_url}/sources", data={"title": ""}, files={"file": (filename, content)})
    assert response.status_code == 200
    assert kind in response.text and filename in response.text and "Passage 1 · Devices" in response.text


def test_text_pdf_upload_keeps_page_numbers(client):
    pdf = make_text_pdf([
        ["A router is a device that forwards packets between networks.",
         "It reads the destination address in every packet."],
        ["A switch is a device that forwards frames inside one network.",
         "It learns which address is reachable through each port."],
    ])
    deck_url = new_deck(client)
    response = client.post(f"{deck_url}/sources", data={"title": "PDF notes"},
                           files={"file": ("notes.pdf", pdf, "application/pdf")})
    assert response.status_code == 200
    assert "a PDF" in response.text and "page 1" in response.text
    assert "A router is a device that forwards packets between networks." in response.text


@pytest.mark.parametrize("data, files, message", [
    ({"text": "   "}, None, "The notes are empty"),
    ({}, {"file": ("scan.pdf", make_blank_pdf(), "application/pdf")}, "does not do OCR"),
    ({}, {"file": ("notes.docx", b"PK\x03\x04", "application/octet-stream")}, "not supported"),
    ({"text": "# Only a heading"}, None, "No passages could be found"),
])
def test_bad_imports_are_refused_with_a_reason(client, data, files, message):
    deck_url = new_deck(client)
    response = client.post(f"{deck_url}/sources", data=data, files=files)
    assert response.status_code == 400
    assert message in response.text
    assert "No notes yet" in client.get(deck_url).text


def test_notes_are_escaped_not_executed(client):
    nasty = "# Notes\n\n" + "A <script>alert(1)</script> tag is a piece of HTML that runs code in a page. " * 4
    source_url = import_notes(client, new_deck(client), text=nasty)
    page = client.get(source_url).text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page


# --- generation --------------------------------------------------------------------------------

def test_offline_generation_report_and_deck(client):
    deck_url = new_deck(client)
    source_url = import_notes(client, deck_url)
    report = client.post(f"{source_url}/generate", data={"mode": "offline"})
    assert report.status_code == 200
    assert re.search(r"<h1>\d+ cards added, 0 rejected</h1>", report.text)
    assert "Nothing left this computer" in report.text and "What is a router?" in report.text
    deck = client.get(deck_url).text
    assert "What is a router?" in deck and "<mark>A router is a device that forwards packets" in deck


def test_llm_mode_is_refused_when_it_is_off(client):
    source_url = import_notes(client, new_deck(client))
    response = client.post(f"{source_url}/generate", data={"mode": "llm"})
    assert response.status_code == 400 and "No cards were generated" in response.text
    with db(client) as session:
        assert session.scalars(select(Card)).all() == []


def test_mock_llm_run_reports_rejected_cards_and_keeps_grounded_ones(mock_client):
    deck_url = new_deck(mock_client)
    source_url = import_notes(mock_client, deck_url)
    assert "mock</strong> model is active" in mock_client.get(source_url).text
    report = mock_client.post(f"{source_url}/generate", data={"mode": "llm"})
    assert "<h1>3 cards added, 3 rejected</h1>" in report.text
    assert "The quote does not appear in the passage it claims to come from." in report.text
    assert "reason code: quote_not_found" in report.text
    assert "from its routing definitely." in report.text  # the altered quote is shown, struck through
    with db(mock_client) as session:
        cards = session.scalars(select(Card)).all()
        assert len(cards) == 3 and {card.origin for card in cards} == {"mock"}
        assert all(card.supporting_quote in card.source_passage for card in cards)
    assert 'class="chip">mock</span>' in mock_client.get(deck_url).text


def test_invalid_json_from_the_model_adds_nothing(tmp_path, clock):
    with make_client(tmp_path, clock, llm_provider="mock", mock_llm_mode="invalid_json") as broken:
        source_url = import_notes(broken, new_deck(broken))
        report = broken.post(f"{source_url}/generate", data={"mode": "llm"})
        assert "<h1>0 cards added, 3 rejected</h1>" in report.text
        assert "was not valid JSON" in report.text


def test_misconfigured_llm_mode_falls_back_to_offline_and_says_so(tmp_path, clock):
    with make_client(tmp_path, clock, llm_provider="openai_compatible", llm_api_key=None, llm_model="") as app:
        source_url = import_notes(app, new_deck(app))
        page = app.get(source_url).text
        assert "LLM_API_KEY is not set" in page and "Generate cards with the model" not in page
        assert "only offline mode works" in app.get("/privacy").text


# --- review ------------------------------------------------------------------------------------

def test_review_shows_front_and_keeps_the_grounded_back_for_the_flip(client):
    deck_url = deck_with_cards(client)
    page = client.get(f"/review?deck={deck_url.rsplit('/', 1)[1]}")
    assert page.status_code == 200
    assert "Leave" in page.text and "Show answer" in page.text
    assert "<div data-back hidden>" in page.text and "From your notes" in page.text and "<mark>" in page.text
    for label in ("Again", "Hard", "Good", "Easy"):
        assert f'<span class="rate-label">{label}</span>' in page.text
    assert 'data-key="1"' in page.text and 'data-key="4"' in page.text


def test_rating_moves_through_the_queue_and_schedules_with_sm2(client, clock):
    deck_url = deck_with_cards(client)
    deck_id = deck_url.rsplit("/", 1)[1]
    with db(client) as session:
        total = len(session.scalars(select(Card)).all())

    html = client.get(f"/review?deck={deck_id}").text
    first = current_card_id(html)
    assert f"{total} cards left" in html

    html = client.post(f"/review/{first}/rate", data={"rating": 3, "deck": deck_id}).text
    assert f"{total - 1} cards left" in html and "1 done today" in html
    assert current_card_id(html) != first

    for _ in range(total - 1):
        html = client.post(f"/review/{current_card_id(html)}/rate", data={"rating": 3, "deck": deck_id}).text
    assert "Done for today." in html and f"You reviewed {total} cards" in html

    with db(client) as session:
        card = session.get(Card, first)
        assert (card.repetitions, card.interval_days, card.due_date) == (1, 1, (START + timedelta(days=1)).date())

    assert "Nothing is due today." in client.get("/").text
    clock.now = START + timedelta(days=1)
    assert f"<strong>{total} cards</strong> due today" in client.get("/").text
    client.post(f"/review/{first}/rate", data={"rating": 3, "deck": deck_id})
    with db(client) as session:
        card = session.get(Card, first)
        assert (card.repetitions, card.interval_days) == (2, 6)


def test_again_brings_the_card_back_and_a_double_press_is_ignored(client):
    deck_url = deck_with_cards(client)
    deck_id = deck_url.rsplit("/", 1)[1]
    html = client.get(f"/review?deck={deck_id}").text
    first = current_card_id(html)

    html = client.post(f"/review/{first}/rate", data={"rating": 3, "deck": deck_id}).text
    client.post(f"/review/{first}/rate", data={"rating": 3, "deck": deck_id})  # the same press, twice
    with db(client) as session:
        assert len(session.scalars(select(Review).where(Review.card_id == first)).all()) == 1

    second = current_card_id(html)
    html = client.post(f"/review/{second}/rate", data={"rating": 1, "deck": deck_id}).text
    while "Done for today." not in html:
        card_id = current_card_id(html)
        if card_id == second:
            assert "again today" in html and "due tomorrow" in html  # schedule already set
        html = client.post(f"/review/{card_id}/rate", data={"rating": 3, "deck": deck_id}).text
    with db(client) as session:
        reviews = session.scalars(select(Review).where(Review.card_id == second).order_by(Review.id)).all()
        assert [(r.rating, r.scheduled) for r in reviews] == [(1, True), (3, False)]
        assert session.get(Card, second).ease_factor == 2.18


def test_review_of_all_decks_and_unknown_deck(client):
    deck_with_cards(client)
    assert "Show answer" in client.get("/review").text
    assert client.get("/review?deck=999").status_code == 404


# --- quiz --------------------------------------------------------------------------------------

def option_values(html: str) -> list[str]:
    return re.findall(r'<button class="option" name="answer" value="([^"]*)"', html)


def test_multiple_choice_question_and_answers(client):
    deck_url = deck_with_cards(client)
    deck_id = deck_url.rsplit("/", 1)[1]
    page = client.get(f"{deck_url}/quiz?mode=mc").text
    card_id = int(re.search(r'name="card_id" value="(\d+)"', page).group(1))
    options = option_values(page)
    with db(client) as session:
        card = session.get(Card, card_id)
        answers = {c.back for c in session.scalars(select(Card).where(Card.deck_id == card.deck_id))}
        correct, state = card.back, (card.due_date, card.ease_factor, card.last_reviewed_at)
    assert 2 <= len(options) <= 4 and len(set(options)) == len(options)
    assert options.count(correct) == 1 and set(options) <= answers

    wrong = next(option for option in options if option != correct)
    feedback = client.post("/quiz/answer", data={"card_id": card_id, "mode": "mc", "answer": wrong,
                                                 "number": 1, "right": 0}).text
    assert "Not quite" in feedback and "0 of 1 right" in feedback and "<mark>" in feedback
    feedback = client.post("/quiz/answer", data={"card_id": card_id, "mode": "mc", "answer": correct,
                                                 "number": 2, "right": 0}).text
    assert "Correct" in feedback and "1 of 2 right" in feedback

    following = client.get(f"/quiz/question?deck={deck_id}&mode=mc&number=3&right=1&previous={card_id}").text
    assert int(re.search(r'name="card_id" value="(\d+)"', following).group(1)) != card_id
    with db(client) as session:
        attempts = session.scalars(select(QuizAttempt).order_by(QuizAttempt.id)).all()
        assert [(a.mode, a.correct) for a in attempts] == [("mc", False), ("mc", True)]
        card = session.get(Card, card_id)
        assert (card.due_date, card.ease_factor, card.last_reviewed_at) == state  # schedule untouched


def test_typed_quiz_uses_the_similarity_check_and_can_be_overruled(client):
    deck_url = deck_with_cards(client)
    page = client.get(f"{deck_url}/quiz?mode=typed").text
    assert 'name="answer"' in page and "compared with the card's answer as text" in page
    with db(client) as session:
        card = session.scalars(select(Card).where(Card.front == "An IPv4 address is _____ bits long and an "
                                                  "IPv6 address is 128 bits long, which is a far larger space.")).one()
        router = session.scalars(select(Card).where(Card.front == "What is a router?")).one()

    exact = client.post("/quiz/answer", data={"card_id": card.id, "mode": "typed", "answer": " 32 ",
                                              "number": 1, "right": 0}).text
    assert "Correct" in exact and "the same after ignoring capitals" in exact

    miss = client.post("/quiz/answer", data={"card_id": card.id, "mode": "typed", "answer": "33",
                                             "number": 1, "right": 0}).text
    assert "Not quite" in miss and "answers with numbers must match exactly" in miss

    answer = router.back.replace("packets", "packts")
    close = client.post("/quiz/answer", data={"card_id": router.id, "mode": "typed", "answer": answer,
                                              "number": 1, "right": 0}).text
    assert "Correct" in close and "which passes the 85% mark" in close and "not a judgement of meaning" in close

    attempt_id = int(re.search(r"/quiz/attempts/(\d+)/override", miss).group(1))
    overruled = client.post(f"/quiz/attempts/{attempt_id}/override",
                            data={"answer": "33", "number": 1, "right": 0}).text
    assert "Correct" in overruled and "You overruled the text comparison." in overruled and "1 of 1 right" in overruled
    with db(client) as session:
        attempt = session.get(QuizAttempt, attempt_id)
        assert attempt.correct and attempt.overridden


def test_quiz_needs_enough_cards(client):
    deck_url = new_deck(client, "Empty")
    assert "Not enough cards for this quiz yet." in client.get(f"{deck_url}/quiz?mode=mc").text
    assert "Not enough cards for this quiz yet." in client.get(f"{deck_url}/quiz?mode=typed").text


# --- deck management ---------------------------------------------------------------------------

def test_search_tag_and_kind_filters(client):
    deck_url = deck_with_cards(client)
    everything = client.get(f"{deck_url}/cards").text
    assert "What is a router?" in everything and "What is an IP address?" in everything

    found = client.get(f"{deck_url}/cards", params={"q": "MAC address"}).text
    assert "What is a router?" not in found and "MAC address" in found

    assert "No cards match." in client.get(f"{deck_url}/cards", params={"q": "zebra"}).text

    tagged = client.get(f"{deck_url}/cards", params={"tag": "addresses"}).text
    assert "What is an IP address?" in tagged and "What is a router?" not in tagged

    clozes = client.get(f"{deck_url}/cards", params={"kind": "cloze"}).text
    assert "_____" in clozes and "What is a router?" not in clozes
    page = client.get(deck_url, params={"tag": "devices"}).text
    assert 'class="chip on" href' in page and "What is an IP address?" not in page


def test_edit_card_checks_the_quote_and_delete_removes_it(client):
    deck_url = deck_with_cards(client)
    with db(client) as session:
        card_id = session.scalars(select(Card).where(Card.front == "What is a router?")).one().id

    form = client.get(f"/cards/{card_id}/edit").text
    assert "Must be copied from the passage below" in form and "Home routers usually join" in form

    bad = client.put(f"/cards/{card_id}", data={"front": "What is a router?", "back": "A box",
                                                "quote": "A router is a magic box that does everything.",
                                                "tags": ""}).text
    assert "The supporting quote was not accepted." in bad and "does not appear in the passage" in bad
    with db(client) as session:
        assert session.get(Card, card_id).back != "A box"

    good = client.put(f"/cards/{card_id}", data={
        "front": "What does a router do?", "back": "It forwards packets between networks",
        "quote": "forwards packets between different networks", "tags": "exam, week 1"}).text
    assert "What does a router do?" in good and "<mark>forwards packets between different networks</mark>" in good
    assert 'class="chip">exam</span>' in good and 'class="chip">week-1</span>' in good
    assert "What does a router do?" in client.get(f"/cards/{card_id}").text

    assert client.delete(f"/cards/{card_id}").text == ""
    assert client.get(f"/cards/{card_id}").status_code == 404
    assert "What does a router do?" not in client.get(deck_url).text


def test_rename_and_delete_deck_and_delete_notes(client):
    deck_url = deck_with_cards(client)
    client.post(f"{deck_url}/edit", data={"name": "Networks 101", "description": "Term 1"})
    page = client.get(deck_url).text
    assert "<h1>Networks 101</h1>" in page and "Term 1" in page

    source_url = re.search(r'href="(/sources/\d+)"', page).group(1)
    assert client.post(f"{source_url}/delete").status_code == 200
    page = client.get(deck_url).text
    assert "No notes yet" in page and "What is a router?" in page  # cards outlive their notes

    client.post(f"{deck_url}/delete")
    assert client.get(deck_url).status_code == 404
    with db(client) as session:
        assert session.scalars(select(Card)).all() == []


def test_export_csv_for_anki(client):
    deck_url = deck_with_cards(client)
    response = client.get(f"{deck_url}/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "networking-anki.csv" in response.headers["content-disposition"]
    lines = response.text.split("\n")
    assert lines[0] == "#separator:Comma" and "#deck:Networking" in lines
    rows = list(csv.reader(io.StringIO("\n".join(line for line in lines if not line.startswith("#")))))
    with db(client) as session:
        assert len(rows) == len(session.scalars(select(Card)).all())
    router = next(row for row in rows if row[0] == "What is a router?")
    assert router[1].startswith("A device that forwards packets between different networks<br><br>")
    assert "From your notes" in router[1] and router[2] == "devices"


# --- progress, privacy, safety -----------------------------------------------------------------

def test_progress_counts_only_real_reviews(client, clock):
    deck_url = deck_with_cards(client)
    deck_id = deck_url.rsplit("/", 1)[1]
    page = client.get("/progress").text
    assert "No reviews in the last 30 days." in page and "Not enough reviews yet." in page

    html = client.get(f"/review?deck={deck_id}").text
    rated = []
    for _ in range(3):
        rated.append(current_card_id(html))
        html = client.post(f"/review/{rated[-1]}/rate", data={"rating": 3, "deck": deck_id}).text
    page = client.get("/progress").text
    assert "3 reviews in the last 30 days." in page and "3 reviews done" in page
    assert "Not enough reviews yet." in page  # first looks at new cards are not retention

    clock.now = START + timedelta(days=1)
    client.post(f"/review/{rated[0]}/rate", data={"rating": 3, "deck": deck_id})
    client.post(f"/review/{rated[1]}/rate", data={"rating": 1, "deck": deck_id})
    client.post(f"/review/{rated[2]}/rate", data={"rating": 4, "deck": deck_id})
    page = client.get("/progress").text
    assert "2 of 3 remembered (67%)" in page
    assert "6 reviews in the last 30 days." in page
    assert page.count('<span class="bar"') == 2  # two days with reviews, two bars
    assert "counted from the 6 reviews stored" in page


def test_privacy_page_states_what_is_sent(client, tmp_path, clock):
    page = client.get("/privacy").text
    assert "Nothing leaves the machine." in page and "does not do" not in page
    assert "Offline mode. Nothing leaves this computer." in page
    with make_client(tmp_path / "llm", clock, llm_provider="openai_compatible", llm_api_key="sk-secret-123",
                     llm_model="some-model", llm_base_url="https://api.groq.com/openai/v1") as llm:
        page = llm.get("/privacy").text
        assert "are sent to api.groq.com" in page and "sk-secret-123" not in page
        source_url = import_notes(llm, new_deck(llm))
        source = llm.get(source_url).text
        assert "This sends your notes to api.groq.com." in source and "sk-secret-123" not in source


def test_cross_site_posts_are_refused(client):
    refused = client.post("/decks", data={"name": "Evil"}, headers={"origin": "https://evil.example"})
    assert refused.status_code == 403
    refused = client.post("/decks", data={"name": "Evil"}, headers={"sec-fetch-site": "cross-site"})
    assert refused.status_code == 403
    assert "Evil" not in client.get("/decks").text
    allowed = client.post("/decks", data={"name": "Mine"}, headers={"origin": "http://testserver"})
    assert allowed.status_code == 200 and "Mine" in allowed.text


def test_missing_pages_and_empty_names(client):
    missing = client.get("/decks/999")
    assert missing.status_code == 404 and "Not found" in missing.text
    assert client.get("/runs/999").status_code == 404
    unnamed = client.post("/decks", data={"name": "   "})
    assert unnamed.status_code == 400 and "Give the deck a name." in unnamed.text
