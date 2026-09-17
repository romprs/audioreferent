"""Разбор дат, времени, длительности и повторения из русской речи — для
голосовых команд redmail_* (например: "перенеси встречу совещание на
десятое сентября в пятнадцать тридцать", "продолжительность два часа",
"повторять каждую неделю"). Здесь намеренно нет общего NLU, только
грамматика, нужная для этих команд.

Даты: относительные ("сегодня"/"завтра"/"послезавтра", "в понедельник",
"следующий вторник", "через неделю") и абсолютные "<день> <месяц> [<год>]"
(день — цифрой или порядковым словом; год не назван — всегда текущий, так
договорились с пользователем). Время: "в/на X [часов] [Y [минут]]" словами
или цифрами, "полдень"/"полночь".

Работает по уже нормализованному тексту (см. commands.normalize) — без
знаков препинания, в нижнем регистре, слова разделены одним пробелом. Из-за
этого "15:00"/"15.00" на входе (двоеточие/точка вырезаны normalize()) уже
превращаются в слитный токен "1500" — учтено ниже отдельным правилом."""

from __future__ import annotations

from datetime import date as date_cls
from datetime import timedelta

_UNITS = {
    "ноль": 0, "один": 1, "одна": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
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
# Родительный падеж («пятнадцатого сентября», «отмени встречу
# пятнадцатого») — так дата звучит в живой речи не реже именительного.
_DAY_ORDINALS.update(
    {
        "первого": 1, "второго": 2, "третьего": 3, "четвёртого": 4, "четвертого": 4,
        "пятого": 5, "шестого": 6, "седьмого": 7, "восьмого": 8, "девятого": 9,
        "десятого": 10, "одиннадцатого": 11, "двенадцатого": 12, "тринадцатого": 13,
        "четырнадцатого": 14, "пятнадцатого": 15, "шестнадцатого": 16,
        "семнадцатого": 17, "восемнадцатого": 18, "девятнадцатого": 19,
        "двадцатого": 20, "двадцать первого": 21, "двадцать второго": 22,
        "двадцать третьего": 23, "двадцать четвёртого": 24, "двадцать четвертого": 24,
        "двадцать пятого": 25, "двадцать шестого": 26, "двадцать седьмого": 27,
        "двадцать восьмого": 28, "двадцать девятого": 29, "тридцатого": 30,
        "тридцать первого": 31,
    }
)
# Отсортировано по числу слов по убыванию — двухсловные формы должны
# проверяться раньше односложных, хотя в данном наборе коллизий и нет.
_DAY_ORDINALS_BY_LENGTH = sorted(_DAY_ORDINALS.items(), key=lambda kv: -len(kv[0].split()))

_RELATIVE_DAYS = {"послезавтра": 2, "завтра": 1, "сегодня": 0}
# «перенеси завтрашнюю планёрку», «отмени сегодняшнее совещание»
_RELATIVE_DAY_ADJECTIVES = (("послезавтрашн", 2), ("завтрашн", 1), ("сегодняшн", 0))
# Часть суток после времени: «в девять вечера» — 21:00, «в два дня» — 14:00.
_EVENING_WORDS = ("вечера", "вечером")
_AFTERNOON_WORDS = ("дня", "днём", "днем")
_MORNING_WORDS = ("утра", "утром")
_NIGHT_WORDS = ("ночи", "ночью")

# Дни недели во всех падежных формах, которые встречаются после "в"/"на"/
# "следующий": понедельник/понедельника, среда/среду и т.п.
_WEEKDAYS = {
    0: ("понедельник", "понедельника", "понедельнику"),
    1: ("вторник", "вторника", "вторнику"),
    2: ("среда", "среду", "среды", "среде"),
    3: ("четверг", "четверга", "четвергу"),
    4: ("пятница", "пятницу", "пятницы", "пятнице"),
    5: ("суббота", "субботу", "субботы", "субботе"),
    6: ("воскресенье", "воскресенья", "воскресенью"),
}
_WEEKDAY_BY_WORD = {word: weekday for weekday, words in _WEEKDAYS.items() for word in words}
_WEEKDAY_MODIFIERS = ("следующ", "ближайш", "будущ")
_TIME_PREPOSITIONS = ("в", "во", "на")

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
    (двузначные токены полезны для ручного тестирования командой
    audioreferent test-command, где проще напечатать "15", чем "пятнадцать")."""
    if start < len(words) and words[start].isdigit() and len(words[start]) <= 2:
        return int(words[start]), start + 1
    return _number_from_words(words, start)


def _year_for(today: date_cls, month: int, day: int) -> int:
    """Год не назван — смотрим вперёд: дата, которая в этом году уже прошла,
    — это следующий год («первого января», сказанное в сентябре)."""
    try:
        return today.year + 1 if date_cls(today.year, month, day) < today else today.year
    except ValueError:
        return today.year


def _month_day_ahead(today: date_cls, day: int) -> date_cls | None:
    """Число без месяца («на двадцатое») — ближайшее такое число, начиная с
    сегодняшнего: в этом месяце, если ещё не прошло, иначе в следующем."""
    year, month = today.year, today.month
    for _ in range(3):  # 31-го может не быть в следующем месяце
        try:
            candidate = date_cls(year, month, day)
        except ValueError:
            candidate = None
        if candidate is not None and candidate >= today:
            return candidate
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return None


def _match_date_tokens(
    words: list[str], today: date_cls
) -> tuple[date_cls | None, tuple[int, int] | None]:
    """(дата, (начало, конец)) — полуоткрытый диапазон индексов слов,
    распознанных как дата, либо (None, None), если даты в тексте нет."""
    n = len(words)

    for i, word in enumerate(words):
        if word in _RELATIVE_DAYS:
            return today + timedelta(days=_RELATIVE_DAYS[word]), (i, i + 1)
        for stem, days in _RELATIVE_DAY_ADJECTIVES:
            if word.startswith(stem):
                return today + timedelta(days=days), (i, i + 1)

    # "через неделю" — ровно через семь дней
    for i in range(n - 1):
        if words[i] == "через" and words[i + 1] == "неделю":
            return today + timedelta(days=7), (i, i + 2)

    # "в понедельник", "следующий вторник", "в следующую среду" — ближайший
    # такой день строго после сегодняшнего (сказанное в понедельник "в
    # понедельник" — это через неделю, а не сегодня).
    for i, word in enumerate(words):
        weekday = _WEEKDAY_BY_WORD.get(word)
        if weekday is None:
            continue
        start = i
        if start > 0 and words[start - 1].startswith(_WEEKDAY_MODIFIERS):
            start -= 1
        if start > 0 and words[start - 1] in ("в", "во"):
            start -= 1
        ahead = (weekday - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead), (start, i + 1)

    for i, word in enumerate(words):
        if word.isdigit() and 1 <= len(word) <= 2 and i + 1 < n and words[i + 1] in _MONTHS:
            day = int(word)
            month = _MONTHS[words[i + 1]]
            end = i + 2
            year = None
            if end < n and words[end].isdigit() and len(words[end]) == 4:
                year = int(words[end])
                end += 1
            year = year if year is not None else _year_for(today, month, day)
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
                year = year if year is not None else _year_for(today, month, day)
                try:
                    return date_cls(year, month, day), (i, end)
                except ValueError:
                    return None, None

    # Число без месяца: «на двадцатое», «двадцать пятого» — ближайшее вперёд.
    for phrase, day in _DAY_ORDINALS_BY_LENGTH:
        phrase_words = phrase.split()
        span = len(phrase_words)
        for i in range(n - span + 1):
            if words[i : i + span] == phrase_words:
                value = _month_day_ahead(today, day)
                if value is None:
                    return None, None
                start = i - 1 if i > 0 and words[i - 1] in ("на", "в", "до") else i
                return value, (start, i + span)

    return None, None


def _apply_part_of_day(hour: int, minute: int, words: list[str], end: int) -> tuple[tuple[int, int], int]:
    """Слово части суток сразу после времени: переводит час и съедается."""
    if end < len(words):
        word = words[end]
        if word in _EVENING_WORDS and hour < 12:
            return (hour + 12, minute), end + 1
        if word in _AFTERNOON_WORDS and hour < 12:
            return ((hour + 12) if hour <= 6 else hour, minute), end + 1
        if word in _NIGHT_WORDS:
            return (0 if hour == 12 else hour, minute), end + 1
        if word in _MORNING_WORDS:
            return (0 if hour == 12 else hour, minute), end + 1
    return (hour, minute), end


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
        if word not in _TIME_PREPOSITIONS:
            continue
        hour, nxt = _number_or_digit(words, i + 1)
        if hour is None or not (0 <= hour <= 23):
            continue
        if nxt < n and words[nxt] in _MONTHS:
            continue  # "на 15 сентября" — это дата, не время
        if nxt < n and words[nxt].startswith(_HOUR_WORD_PREFIX):
            nxt += 1
        minute, nxt2 = _number_or_digit(words, nxt)
        if minute is not None and 0 <= minute <= 59:
            end = nxt2
            if end < n and words[end].startswith(_MINUTE_WORD_PREFIX):
                end += 1
        else:
            minute = 0
            end = nxt
        value, end = _apply_part_of_day(hour, minute, words, end)
        return value, (i, end)

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
    тридцать", "на восемь тридцать"), "полдень"/"полночь". None — времени
    в тексте нет."""
    value, _span = _match_time_tokens(text.split())
    return value


def extract(text: str, *, today: date_cls | None = None) -> tuple[str, date_cls | None, tuple[int, int] | None]:
    """Достаёт из текста дату и время; возвращает (остаток текста без них —
    то, что дальше считается темой события, дата, время). Дата вырезается
    первой, время ищется уже без неё — иначе "на 15 сентября" читалось бы
    и как 15:00. Одинокий предлог ("на"/"в"), оставшийся сразу перед
    вырезанным куском, тоже убирается."""
    today = today or date_cls.today()
    words = text.split()
    date_value, date_span = _match_date_tokens(words, today)
    if date_span is not None:
        del words[date_span[0] : date_span[1]]
    time_value, time_span = _match_time_tokens(words)
    if time_span is not None:
        del words[time_span[0] : time_span[1]]
    while words and words[-1] in ("на", "в", "во"):
        words.pop()

    return " ".join(words).strip(), date_value, time_value


def parse_duration(text: str) -> int | None:
    """Длительность в минутах: "два часа", "полтора часа", "полчаса", "час",
    "сорок пять минут", "два часа тридцать минут", "два с половиной часа".
    None — не похоже на длительность."""
    words = text.split()
    if not words:
        return None
    if "полчаса" in words:
        return 30
    if "полтора" in words:
        return 90

    minutes: int | None = None
    i = 0
    n = len(words)
    while i < n:
        value, nxt = _number_or_digit(words, i)
        if value is None:
            if words[i].startswith(_HOUR_WORD_PREFIX):
                # "час" без числа — один час
                minutes = (minutes or 0) + 60
                i += 1
                continue
            i += 1
            continue
        if nxt < n and words[nxt] == "с" and nxt + 1 < n and words[nxt + 1] == "половиной":
            nxt += 2
            minutes = (minutes or 0) + value * 60 + 30
            if nxt < n and words[nxt].startswith(_HOUR_WORD_PREFIX):
                nxt += 1
            i = nxt
            continue
        if nxt < n and words[nxt].startswith(_HOUR_WORD_PREFIX):
            minutes = (minutes or 0) + value * 60
            i = nxt + 1
            continue
        if nxt < n and words[nxt].startswith(_MINUTE_WORD_PREFIX):
            minutes = (minutes or 0) + value
            i = nxt + 1
            continue
        i = nxt
    return minutes if minutes else None


_RECURRENCE_PHRASES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("нет", "не повторять", "без повторения", "без повторений", "однократно", "один раз"), "none"),
    (("каждый день", "ежедневно", "по будням"), "daily"),
    (("каждую неделю", "еженедельно", "раз в неделю", "каждой недели"), "weekly"),
    (("каждый месяц", "ежемесячно", "раз в месяц"), "monthly"),
    (("каждый год", "ежегодно", "раз в год"), "yearly"),
)


def parse_recurrence(text: str) -> str | None:
    """"каждую неделю" -> "weekly" (значения — как у recurrence в
    event_form_set redmail: none/daily/weekly/monthly/yearly). None —
    не похоже ни на одно из известных повторений."""
    padded = f" {text.strip()} "
    for phrases, value in _RECURRENCE_PHRASES:
        if any(f" {phrase} " in padded for phrase in phrases):
            return value
    return None
