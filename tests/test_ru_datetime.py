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


def test_absolute_date_ordinal_genitive():
    # «отмени встречу тест пятнадцатого сентября», «на двадцать первого»
    assert ru_datetime.parse_date("пятнадцатого сентября", today=TODAY) == date(2026, 9, 15)
    assert ru_datetime.parse_date("двадцать первого сентября", today=TODAY) == date(2026, 9, 21)
    subject, on_date, _ = ru_datetime.extract("тест пятнадцатого сентября", today=TODAY)
    assert (subject, on_date) == ("тест", date(2026, 9, 15))


def test_date_without_year_looks_ahead():
    # год не назван -> ближайшая такая дата вперёд: прошедшая — в следующем году
    assert ru_datetime.parse_date("1 января", today=TODAY) == date(2027, 1, 1)
    assert ru_datetime.parse_date("10 декабря", today=TODAY) == date(2026, 12, 10)
    assert ru_datetime.parse_date("8 сентября", today=TODAY) == date(2026, 9, 8)  # сегодня — не прошла


def test_weekday_is_next_such_day_strictly_after_today():
    # TODAY = вторник 8 сентября
    assert ru_datetime.parse_date("в понедельник", today=TODAY) == date(2026, 9, 14)
    assert ru_datetime.parse_date("следующий понедельник", today=TODAY) == date(2026, 9, 14)
    assert ru_datetime.parse_date("в следующую среду", today=TODAY) == date(2026, 9, 9)
    assert ru_datetime.parse_date("во вторник", today=TODAY) == date(2026, 9, 15)  # тот же день -> через неделю
    assert ru_datetime.parse_date("в пятницу", today=TODAY) == date(2026, 9, 11)


def test_in_a_week():
    assert ru_datetime.parse_date("через неделю", today=TODAY) == date(2026, 9, 15)


def test_extract_strips_weekday_phrase_with_modifier_and_preposition():
    subject, on_date, on_time = ru_datetime.extract(
        "планёрка в следующий понедельник в восемь тридцать", today=TODAY
    )
    assert subject == "планёрка"
    assert on_date == date(2026, 9, 14)
    assert on_time == (8, 30)


def test_time_after_na_preposition():
    assert ru_datetime.parse_time("на восемь тридцать") == (8, 30)


def test_digit_date_after_na_is_not_a_time():
    assert ru_datetime.parse_time("на 15 сентября") is None
    subject, on_date, on_time = ru_datetime.extract("планёрка на 15 сентября на восемь тридцать", today=TODAY)
    assert (subject, on_date, on_time) == ("планёрка", date(2026, 9, 15), (8, 30))


def test_duration():
    assert ru_datetime.parse_duration("два часа") == 120
    assert ru_datetime.parse_duration("2 часа") == 120
    assert ru_datetime.parse_duration("час") == 60
    assert ru_datetime.parse_duration("полчаса") == 30
    assert ru_datetime.parse_duration("полтора часа") == 90
    assert ru_datetime.parse_duration("сорок пять минут") == 45
    assert ru_datetime.parse_duration("два часа тридцать минут") == 150
    assert ru_datetime.parse_duration("два с половиной часа") == 150
    assert ru_datetime.parse_duration("долго") is None


def test_recurrence():
    assert ru_datetime.parse_recurrence("каждую неделю") == "weekly"
    assert ru_datetime.parse_recurrence("еженедельно") == "weekly"
    assert ru_datetime.parse_recurrence("каждый день") == "daily"
    assert ru_datetime.parse_recurrence("каждый месяц") == "monthly"
    assert ru_datetime.parse_recurrence("каждый год") == "yearly"
    assert ru_datetime.parse_recurrence("нет") == "none"
    assert ru_datetime.parse_recurrence("не повторять") == "none"
    assert ru_datetime.parse_recurrence("по пятницам") is None


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


def test_relative_day_adjectives():
    # TODAY = вторник 8 сентября
    assert ru_datetime.extract("завтрашнюю планёрку", today=TODAY) == ("планёрку", date(2026, 9, 9), None)
    assert ru_datetime.parse_date("сегодняшнее совещание", today=TODAY) == date(2026, 9, 8)
    assert ru_datetime.parse_date("послезавтрашний отчёт", today=TODAY) == date(2026, 9, 10)


def test_day_of_month_without_month_looks_ahead():
    assert ru_datetime.parse_date("на двадцатое", today=TODAY) == date(2026, 9, 20)
    assert ru_datetime.extract("двадцать пятого в десять", today=TODAY) == ("", date(2026, 9, 25), (10, 0))
    assert ru_datetime.parse_date("первого", today=TODAY) == date(2026, 10, 1)  # 1 сентября прошло
    assert ru_datetime.parse_date("восьмое", today=TODAY) == date(2026, 9, 8)  # сегодня


def test_part_of_day_after_time():
    assert ru_datetime.parse_time("в девять вечера") == (21, 0)
    assert ru_datetime.parse_time("в два дня") == (14, 0)
    assert ru_datetime.parse_time("в одиннадцать дня") == (11, 0)
    assert ru_datetime.parse_time("в восемь утра") == (8, 0)
    assert ru_datetime.parse_time("в двенадцать ночи") == (0, 0)
    assert ru_datetime.extract("завтра в 9 вечера", today=TODAY) == ("", date(2026, 9, 9), (21, 0))

