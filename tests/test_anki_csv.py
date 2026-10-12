import csv
import io

from app.export.anki_csv import ExportCard, anki_tag, deck_to_anki_csv

CARDS = [
    ExportCard(front="What is a router?", back="A device that forwards packets",
               quote="A **router** is a device\nthat forwards packets between networks.",
               tags=("devices", "week 1")),
    ExportCard(front='Why is "a < b", here?', back="Line one\nLine two",
               quote="Commas, \"quotes\" & <tags> are kept.", tags=()),
    ExportCard(front="Qu'est-ce qu'un réseau ? 网络", back="Un groupe d'appareils",
               quote="Un réseau est un groupe d'appareils.", tags=("français",)),
]


def parse(text: str):
    lines = text.split("\n")
    headers = [line for line in lines if line.startswith("#")]
    body = "\n".join(line for line in lines if not line.startswith("#"))
    return headers, list(csv.reader(io.StringIO(body)))


def test_headers_tell_anki_how_to_read_the_file():
    headers, _ = parse(deck_to_anki_csv("Networking  basics", CARDS))
    assert headers == [
        "#separator:Comma",
        "#html:true",
        "#notetype:Basic",
        "#deck:Networking basics",
        "#columns:Front,Back,Tags",
        "#tags column:3",
    ]


def test_one_row_of_three_fields_per_card():
    _, rows = parse(deck_to_anki_csv("Deck", CARDS))
    assert len(rows) == 3 and all(len(row) == 3 for row in rows)
    assert rows[0][0] == "What is a router?"


def test_back_holds_the_answer_and_the_supporting_quote():
    _, rows = parse(deck_to_anki_csv("Deck", CARDS))
    assert rows[0][1] == (
        "A device that forwards packets<br><br><i>From your notes:</i> "
        "&ldquo;A router is a device that forwards packets between networks.&rdquo;"
    )


def test_html_is_escaped_and_line_breaks_become_br():
    text = deck_to_anki_csv("Deck", CARDS)
    _, rows = parse(text)
    assert rows[1][0] == 'Why is "a &lt; b", here?'
    assert rows[1][1].startswith("Line one<br>Line two<br><br>")
    assert "Commas, \"quotes\" &amp; &lt;tags&gt; are kept." in rows[1][1]
    # every record is on one physical line, so no field contains a raw newline
    assert len([line for line in text.split("\n") if line and not line.startswith("#")]) == 3


def test_tags_are_space_separated_without_inner_spaces():
    _, rows = parse(deck_to_anki_csv("Deck", CARDS))
    assert rows[0][2] == "devices week_1"
    assert rows[1][2] == ""
    assert anki_tag("  two  words ") == "two_words"


def test_unicode_survives_and_the_file_encodes_as_utf8():
    text = deck_to_anki_csv("Deck", CARDS)
    _, rows = parse(text)
    assert rows[2][0] == "Qu'est-ce qu'un réseau ? 网络" and rows[2][2] == "français"
    assert text.encode("utf-8").decode("utf-8") == text


def test_empty_deck_is_just_the_headers():
    headers, rows = parse(deck_to_anki_csv("Empty", []))
    assert len(headers) == 6 and rows == []
