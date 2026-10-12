from app.ingestion.splitter import looks_like_heading, split_passages
from app.text import sentence_spans

LONG = ("Packets travel through several routers before they reach their destination. " * 4).strip()

MARKDOWN = f"""# Networking

## Addresses

An IP address identifies a device on a network. {LONG}

A MAC address identifies a network interface. {LONG}

## Ports

A port number identifies an application on a device. {LONG}
"""


def assert_offsets(text, passages):
    for passage in passages:
        assert text[passage.start_char:passage.end_char] == passage.text
        assert passage.text == passage.text.strip()
    assert [p.ordinal for p in passages] == list(range(len(passages)))


def test_markdown_headings_become_section_titles():
    text = MARKDOWN.strip()
    passages = split_passages(text)
    assert [p.section_title for p in passages] == ["Addresses", "Addresses", "Ports"]
    assert passages[0].text.startswith("An IP address")
    assert passages[2].text.startswith("A port number")
    assert_offsets(text, passages)


def test_heading_lines_are_not_part_of_any_passage():
    passages = split_passages(MARKDOWN.strip())
    assert all("#" not in p.text for p in passages)


def test_short_paragraphs_merge_within_a_section():
    text = "# Topic\n\nFirst short paragraph.\n\nSecond short paragraph.\n\nThird short paragraph."
    passages = split_passages(text)
    assert len(passages) == 1
    assert passages[0].text.startswith("First") and passages[0].text.endswith("Third short paragraph.")
    assert_offsets(text, passages)


def test_short_paragraphs_do_not_merge_across_sections():
    text = "# One\n\nShort paragraph in one.\n\n# Two\n\nShort paragraph in two."
    passages = split_passages(text)
    assert [(p.section_title, p.text) for p in passages] == [
        ("One", "Short paragraph in one."),
        ("Two", "Short paragraph in two."),
    ]


def test_short_leftover_joins_the_previous_passage():
    text = f"# Topic\n\n{LONG.strip()}\n\nA short closing remark."
    passages = split_passages(text)
    assert len(passages) == 1
    assert passages[0].text.endswith("A short closing remark.")
    assert_offsets(text, passages)


def test_long_paragraph_is_split_at_sentence_boundaries():
    sentence = "Each sentence in this paragraph is about forty characters. "
    text = (sentence * 60).strip()
    passages = split_passages(text, max_chars=500)
    assert len(passages) > 1
    assert all(len(p.text) <= 500 for p in passages)
    assert all(p.text.endswith(".") and p.text.startswith("Each") for p in passages)
    assert_offsets(text, passages)


def test_text_without_headings_has_no_section_title():
    text = "Just one paragraph of notes with no heading at all. It has two sentences."
    passages = split_passages(text)
    assert len(passages) == 1 and passages[0].section_title is None


def test_plain_text_headings_are_detected():
    text = (
        "SUBNETTING\n\nA subnet is a smaller network inside a larger one.\n\n"
        "2.1 Routing basics\n\nA router forwards packets between networks.\n\n"
        "Switches\n\nA switch connects devices inside one network.\n\n"
        "Underlined title\n----------------\n\nText under the underlined title."
    )
    passages = split_passages(text)
    assert [p.section_title for p in passages] == [
        "SUBNETTING", "2.1 Routing basics", "Switches", "Underlined title"
    ]
    assert_offsets(text, passages)


def test_looks_like_heading_is_conservative():
    assert looks_like_heading("Transport layer")
    assert looks_like_heading("3. Error detection")
    assert not looks_like_heading("A router forwards packets between networks.")
    assert not looks_like_heading("- a list item")
    assert not looks_like_heading("TCP is reliable")  # short, but it is a statement
    assert not looks_like_heading("This line has far too many words in it to be a heading")


def test_page_numbers_come_from_page_starts():
    page_one = "Notes on the first page. " * 12
    page_two = "Notes on the second page. " * 12
    text = page_one.strip() + "\n\n" + page_two.strip()
    passages = split_passages(text, page_starts=(0, len(page_one.strip()) + 2))
    assert [p.page for p in passages] == [1, 2]


def test_empty_text_gives_no_passages():
    assert split_passages("") == []


def test_sentence_spans_keep_abbreviations_and_list_items_apart():
    text = "Use a hub, e.g. for a small lab. A switch is better.\n- First item\n- Second item"
    sentences = [text[start:end] for start, end in sentence_spans(text)]
    assert sentences == [
        "Use a hub, e.g. for a small lab.",
        "A switch is better.",
        "- First item",
        "- Second item",
    ]
