import random

from app.quiz.distractors import QuizCard, build_question, pick_distractors

DECK = [
    QuizCard(1, "cloze", "The _____ layer delivers data to the right application.", "transport"),
    QuizCard(2, "cloze", "A _____ forwards packets between networks.", "router"),
    QuizCard(3, "cloze", "A _____ forwards frames inside one network.", "switch"),
    QuizCard(4, "cloze", "The _____ protocol sends datagrams without a handshake.", "UDP"),
    QuizCard(5, "cloze", "An IPv4 address is _____ bits long.", "32"),
    QuizCard(6, "cloze", "An IPv6 address is _____ bits long.", "128"),
    QuizCard(7, "definition", "What is a protocol?", "A set of rules that two devices follow"),
    QuizCard(8, "definition", "What is a port number?", "A 16-bit number that identifies an application"),
    QuizCard(9, "cloze", "Web servers listen on port _____ for HTTPS.", "443"),
    QuizCard(10, "cloze", "A duplicate answer: the _____ sends packets on.", "Router"),
]
BY_ID = {card.card_id: card for card in DECK}


def test_question_has_the_correct_answer_once_and_three_distractors():
    question = build_question(BY_ID[2], DECK, seed=7)
    assert question.card_id == 2 and question.prompt == BY_ID[2].front
    assert len(question.options) == 4 and len(set(question.options)) == 4
    assert question.options.count("router") == 1
    assert question.correct == "router" and question.options[question.correct_index] == "router"


def test_distractors_never_equal_the_correct_answer_even_with_different_case():
    for seed in range(50):
        distractors = pick_distractors(BY_ID[2], DECK, random.Random(seed))
        assert "router" not in [d.lower() for d in distractors]  # card 10's "Router" is the same answer
        assert len(distractors) == len(set(distractors)) == 3


def test_distractors_come_only_from_the_pool_that_was_passed_in():
    answers = {card.back for card in DECK}
    for seed in range(20):
        assert set(pick_distractors(BY_ID[1], DECK, random.Random(seed))) <= answers
    small_pool = [BY_ID[1], BY_ID[2], BY_ID[3]]
    assert set(pick_distractors(BY_ID[1], small_pool, random.Random(0))) == {"router", "switch"}


def test_text_already_shown_in_the_question_is_not_offered_as_an_option():
    target = QuizCard(20, "cloze", "A router and a _____ are both network devices.", "switch")
    for seed in range(30):
        assert "router" not in pick_distractors(target, DECK, random.Random(seed))


def test_numeric_answers_get_numeric_distractors_first():
    for seed in range(20):
        distractors = pick_distractors(BY_ID[5], DECK, random.Random(seed))
        assert {"128", "443"} <= set(distractors)  # the only two other numbers always make the cut


def test_same_kind_and_similar_length_are_preferred():
    for seed in range(20):
        distractors = pick_distractors(BY_ID[7], DECK, random.Random(seed))
        assert "A 16-bit number that identifies an application" in distractors


def test_same_seed_same_question_and_seeds_vary_the_question():
    assert build_question(BY_ID[2], DECK, seed=3) == build_question(BY_ID[2], DECK, seed=3)
    variants = {build_question(BY_ID[2], DECK, seed=seed).options for seed in range(30)}
    assert len(variants) > 1


def test_small_decks_give_fewer_options_or_no_question():
    two = [BY_ID[2], BY_ID[3]]
    question = build_question(BY_ID[2], two, seed=1)
    assert set(question.options) == {"router", "switch"}
    assert build_question(BY_ID[2], [BY_ID[2]], seed=1) is None
    assert build_question(BY_ID[2], [BY_ID[2], BY_ID[10]], seed=1) is None  # only a duplicate answer
