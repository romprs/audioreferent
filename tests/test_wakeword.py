import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audioreferent.wakeword import contains_wake_word, strip_wake_word


def test_exact_match():
    assert contains_wake_word("вика открой браузер", "вика", 1)


def test_fuzzy_match_close_mishearing():
    assert contains_wake_word("ника открой браузер", "вика", 1)


def test_no_match_unrelated_text():
    assert not contains_wake_word("привет как дела", "вика", 1)


def test_multiword_wake_word():
    assert contains_wake_word("окей вика включи музыку", "окей вика", 1)


def test_too_far_no_match():
    assert not contains_wake_word("экскаватор", "вика", 1)


def test_strip_returns_rest_of_phrase():
    assert strip_wake_word("вика привет", "вика", 1) == "привет"


def test_strip_fuzzy_and_middle_position():
    assert strip_wake_word("окей ника открой браузер", "вика", 1) == "окей открой браузер"


def test_strip_wake_word_only_gives_empty_string():
    assert strip_wake_word("вика", "вика", 1) == ""


def test_strip_no_wake_word_gives_none():
    assert strip_wake_word("привет как дела", "вика", 1) is None


def test_strip_multiword_wake_word():
    assert strip_wake_word("окей вика включи музыку", "окей вика", 1) == "включи музыку"
