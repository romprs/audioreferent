import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audioreferent.wakeword import contains_wake_word


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
