"""Разбор дат и времени из русской речи — используется голосовыми командами
redmail_* (например: "перенеси встречу совещание на десятое сентября в
пятнадцать тридцать"). Здесь намеренно нет общего NLU, только грамматика,
нужная для этой одной задачи: относительные даты
("сегодня"/"завтра"/"послезавтра"), абсолютные "<день> <месяц> [<год>]" (день
— цифрой или порядковым словом) и время "чч:мм"/"в X [часов] [Y [минут]]".

Работает по уже нормализованному тексту (см. commands.normalize) — без
знаков препинания, в нижнем регистре, слова разделены одним пробелом. Из-за
этого "15:00"/"15.00" на входе (двоеточие/точка вырезаны normalize()) уже
превращаются в слитный токен "1500" — учтено ниже отдельным правилом."""

from __future__ import annotations

import re
from datetime import date as date_cls
from datetime import timedelta

_UNITS = {
    "ноль": 0, "один": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
}
_TEENS = {
    "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13,
    "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17,
    "восемнадцать": 18, "девятнадцать": 19,
}
_TENS = {"двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50}

_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

# Порядковые формы дня месяца ("десятое сентября") — только последнее слово
# составного числительного меняет форму на порядковую ("двадцать пятое"),
# поэтому проще перечислить все 31 форму, чем собирать словообразование.
_DAY_ORDINALS = {
    "первое": 1, "второе": 2, "третье": 3, "четвёртое": 4, "четвертое": 4,
    "пятое": 5, "шестое": 6, "седьмое": 7, "восьмое": 8, "девятое": 9,
    "десятое": 10, "одиннадцатое": 11, "двенадцатое": 12, "тринадцатое": 13,
    "четырнадцатое": 14, "пятнадцатое": 15, "шестнадцатое": 16,
    "семнадцатое": 17, "восемнадцатое": 18, "девятнадцатое": 19,
    "двадцатое": 20, "двадцать первое": 21, "двадцать второе": 22,
    "двадцать третье": 23, "двадцать четвёртое": 24, "двадцать четвертое": 24,
    "двадцать пятое": 25, "двадцать шестое": 26, "двадцать седьмое": 27,
    "двадцать восьмое": 28, "двадцать девятое": 29, "тридцатое": 30,
    "тридцать первое": 31,
}
# Отсортировано по числу слов по убыванию — двухсловные формы должны
# проверяться раньше односложных, хотя в данном наборе коллизий и нет.
_DAY_ORDINALS_BY_LENGTH = sorted(_DAY_ORDINALS.items(), key=lambda kv: -len(kv[0].split()))

_RELATIVE_DAYS = {"послезавтра": 2, "завтра": 1, "сегодня": 0}

_HOUR_WORD_PREFIX = "час"
_MINUTE_WORD_PREFIX = "минут"


def _number_from_words(words: list[str], start: int) -> tuple[int | None, int]:
    """Составное числительное словами, начиная с words[start] (например
    "сорок пять" -> 45). Возвращает (число, индекс следующего
    непрочитанного слова) либо (None, start), если числа тут нет."""
    if start >= len(words):
        return None, start
    word = words[start]
    if word in _TENS:
        value = _TENS[word]
        nxt = start + 1
        if nxt < len(words) and words[nxt] in _UNITS:
            return value + _UNITS[words[nxt]], nxt + 1
        return value, nxt
    if word in _TEENS:
        return _TEENS[word], start + 1
    if word in _UNITS:
        return _UNITS[word], start + 1
    return None, start


def _number_or_digit(words: list[str], start: int) -> tuple[int | None, int]:
    """То же самое, но сперва пробует прочитать голое числительное цифрой
    (двух-трёхзначные токены полезны для ручного тестирования командой
    audioreferent test-command, где проще напечатать "15", чем "пятнадцать")."""
    if start < len(words) and words[start].isdigit() and len(words[start]) <= 2:
        return int(words[start]), start + 1
    return _number_from_words(words, start)


def _infer_year(today: date_cls, month: int, day: int) -> int:
    """Год не назван — берём текущий, а если такая дата в этом году уже
    прошла, значит имелся в виду следующий (переносить встречу "в прошлое"
    было бы бессмысленно)."""
    try:
        candidate = date_cls(today.year, month, day)
    except ValueError:
        return today.year
    return today.year if candidate >= today else today.year + 1


def _match_date_tokens(
    words: list[str], today: date_cls
) -> tuple[date_cls | None, tuple[int, int] | None]:
    """(дата, (начало, конец)) — полуоткрытый диапазон индексов слов,
    распознанных как дата, либо (None, None), если даты в тексте нет."""
    n = len(words)

    for i, word in enumerate(words):
        if word in _RELATIVE_DAYS:
            return today + timedelta(days=_RELATIVE_DAYS[word]), (i, i + 1)

    for i, word in enumerate(words):
        if word.isdigit() and 1 <= len(word) <= 2 and i + 1 < n and words[i + 1] in _MONTHS:
            day = int(word)
            month = _MONTHS[words[i + 1]]
            end = i + 2
            year = None
            if end < n and words[end].isdigit() and len(words[end]) == 4:
                year = int(words[end])
                end += 1
            year = year if year is not None else _infer_year(today, month, day)
            try:
                return date_cls(year, month, day), (i, end)
            except ValueError:
                return None, None

    for phrase, day in _DAY_ORDINALS_BY_LENGTH:
        phrase_words = phrase.split()
        span = len(phrase_words)
        for i in range(n - span):
            if words[i : i + span] == phrase_words and words[i + span] in _MONTHS:
                month = _MONTHS[words[i + span]]
                end = i + span + 1
                year = None
                if end < n and words[end].isdigit() and len(words[end]) == 4:
                    year = int(words[end])
                    end += 1
                year = year if year is not None else _infer_year(today, month, day)
                try:
                    return date_cls(year, month, day), (i, end)
                except ValueError:
                    return None, None

    return None, None


def _match_time_tokens(words: list[str]) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """(время, (начало, конец)) в тех же терминах, что _match_date_tokens."""
    n = len(words)

    for i, word in enumerate(words):
        if word == "полдень":
            return (12, 0), (i, i + 1)
        if word == "полночь":
            return (0, 0), (i, i + 1)

    # normalize() вырезает ":"/"." — "15:00"/"15.00" на входе превращаются
    # в один слитный токен "1500" (или "900" для однозначного часа).
    for i, word in enumerate(words):
        if word.isdigit() and len(word) in (3, 4):
            hour, minute = int(word[:-2]), int(word[-2:])
            if hour <= 23 and minute <= 59:
                return (hour, minute), (i, i + 1)

    for i, word in enumerate(words):
        if word != "в":
            continue
        hour, nxt = _number_or_digit(words, i + 1)
        if hour is None or not (0 <= hour <= 23):
            continue
        if nxt < n and words[nxt].startswith(_HOUR_WORD_PREFIX):
            nxt += 1
        minute, nxt2 = _number_or_digit(words, nxt)
        if minute is not None and 0 <= minute <= 59:
            end = nxt2
        else:
            minute = 0
            end = nxt
        return (hour, minute), (i, end)

    return None, None


def parse_date(text: str, *, today: date_cls | None = None) -> date_cls | None:
    """Дата из текста, либо None, если её там нет вообще (в отличие от
    "дата опущена -> берём текущую" — это решение вызывающей стороны, не
    этой функции: она различает "не сказано" от "сказано, что сегодня")."""
    value, _span = _match_date_tokens(text.split(), today or date_cls.today())
    return value


def parse_time(text: str) -> tuple[int, int] | None:
    """Время из текста: "15:00"/"15.00" (после normalize() — "1500"),
    "в 15 [часов] [30 [минут]]" смешанно и словами ("в пятнадцать
    тридцать"), "полдень"/"полночь". None — времени в тексте нет."""
    value, _span = _match_time_tokens(text.split())
    return value


def extract(text: str, *, today: date_cls | None = None) -> tuple[str, date_cls | None, tuple[int, int] | None]:
    """Достаёт из текста дату и время; возвращает (остаток текста без них —
    то, что дальше считается темой события, дата, время). Одинокий предлог
    ("на"/"в"), оставшийся сразу перед вырезанным куском, тоже убирается."""
    today = today or date_cls.today()
    words = text.split()
    date_value, date_span = _match_date_tokens(words, today)
    time_value, time_span = _match_time_tokens(words)

    for start, end in sorted(filter(None, (date_span, time_span)), key=lambda s: -s[0]):
        del words[start:end]
    while words and words[-1] in ("на", "в"):
        words.pop()

    return " ".join(words).strip(), date_value, time_value
