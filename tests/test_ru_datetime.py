import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audioreferent import ru_datetime

TODAY = date(2026, 9, 8)  # вторник


def test_relative_dates():
    assert ru_datetime.parse_date("сегодня", today=TODAY) == TODAY
    assert ru_datetime.parse_date("завтра", today=TODAY) == date(2026, 9, 9)
    assert ru_datetime.parse_date("послезавтра", today=TODAY) == date(2026, 9, 10)


def test_absolute_date_digit_day():
    assert ru_datetime.parse_date("10 сентября", today=TODAY) == date(2026, 9, 10)


def test_absolute_date_digit_day_with_year():
    assert ru_datetime.parse_date("1 марта 2027", today=TODAY) == date(2027, 3, 1)


def test_absolute_date_ordinal_word_single_word():
    assert ru_datetime.parse_date("десятое сентября", today=TODAY) == date(2026, 9, 10)


def test_absolute_date_ordinal_word_compound():
    assert ru_datetime.parse_date("двадцать пятое сентября", today=TODAY) == date(2026, 9, 25)


def test_date_without_year_rolls_over_to_next_year_if_already_passed():
    # 1 января этого года уже прошло -> следующий год
    assert ru_datetime.parse_date("1 января", today=TODAY) == date(2027, 1, 1)


def test_date_without_year_stays_this_year_if_still_ahead():
    assert ru_datetime.parse_date("10 декабря", today=TODAY) == date(2026, 12, 10)


def test_no_date_returns_none():
    assert ru_datetime.parse_date("просто текст без даты", today=TODAY) is None


def test_time_digits_with_colon_after_normalize():
    # normalize() вырезает ":" -> "15:00" превращается в "1500"
    assert ru_datetime.parse_time("1500") == (15, 0)
    assert ru_datetime.parse_time("900") == (9, 0)


def test_time_word_form():
    assert ru_datetime.parse_time("в пятнадцать тридцать") == (15, 30)
    assert ru_datetime.parse_time("в пятнадцать часов тридцать минут") == (15, 30)
    assert ru_datetime.parse_time("в десять") == (10, 0)


def test_time_digit_after_predlog():
    assert ru_datetime.parse_time("в 15 часов") == (15, 0)


def test_time_polden_polnoch():
    assert ru_datetime.parse_time("полдень") == (12, 0)
    assert ru_datetime.parse_time("полночь") == (0, 0)


def test_no_time_returns_none():
    assert ru_datetime.parse_time("совещание сегодня") is None


def test_extract_removes_date_and_time_and_trailing_preposition():
    subject, on_date, on_time = ru_datetime.extract(
        "совещание завтра в пятнадцать тридцать", today=TODAY
    )
    assert subject == "совещание"
    assert on_date == date(2026, 9, 9)
    assert on_time == (15, 30)


def test_extract_subject_only():
    subject, on_date, on_time = ru_datetime.extract("совещание с отделом продаж", today=TODAY)
    assert subject == "совещание с отделом продаж"
    assert on_date is None
    assert on_time is None


def test_extract_date_only_strips_trailing_na():
    subject, on_date, on_time = ru_datetime.extract("совещание на десятое сентября", today=TODAY)
    assert subject == "совещание"
    assert on_date == date(2026, 9, 10)
    assert on_time is None
