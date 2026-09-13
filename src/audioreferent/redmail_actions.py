"""Голосовые команды, управляющие почтовым клиентом redmail через его
локальный канал IPC (см. redmail_client.py). Ничего из отправляемого
наружу (новая/изменённая/отменённая встреча) не улетает само — redmail
лишь открывает обычный диалог с подтверждением, кнопку жмёт человек
(гарантия на стороне redmail, здесь её нельзя ослабить)."""

from __future__ import annotations

import logging
from datetime import date as date_cls
from datetime import datetime
from typing import Any

from dataclasses import dataclass

from . import ru_datetime
from .actions import ActionError, launch_app
from .config import EventFormWords
from .redmail_client import RedmailError, RedmailNotRunning
from .redmail_client import cancel_event as _redmail_cancel_event
from .redmail_client import create_event as _redmail_create_event
from .redmail_client import event_form_cancel as _redmail_event_form_cancel
from .redmail_client import event_form_open as _redmail_event_form_open
from .redmail_client import event_form_save as _redmail_event_form_save
from .redmail_client import event_form_set as _redmail_event_form_set
from .redmail_client import event_form_state as _redmail_event_form_state
from .redmail_client import contact_picker_accept as _redmail_picker_accept
from .redmail_client import contact_picker_cancel as _redmail_picker_cancel
from .redmail_client import contact_picker_open as _redmail_picker_open
from .redmail_client import contact_picker_select as _redmail_picker_select
from .redmail_client import find_contacts as _redmail_find_contacts
from .redmail_client import find_events as _redmail_find_events
from .redmail_client import focus as _redmail_focus
from .redmail_client import update_event as _redmail_update_event
from .wakeword import strip_wake_word

log = logging.getLogger(__name__)


def _split_on_last_word(words: list[str], marker: str) -> tuple[list[str], list[str]] | None:
    """Индекс последнего вхождения marker как отдельного слова — режем по
    нему на "до"/"после". Последнее, а не первое: в "перенеси встречу ...
    на <новая дата>" целевая дата — это то, что после ПОСЛЕДНЕГО "на"."""
    for i in range(len(words) - 1, -1, -1):
        if words[i] == marker:
            return words[:i], words[i + 1 :]
    return None


def _local_hour_minute(iso_start: str) -> tuple[int, int]:
    local = datetime.fromisoformat(iso_start).astimezone()
    return local.hour, local.minute


_DEFAULT_LAUNCH_CANDIDATES = ["redmail"]


def _launch_redmail(args: dict[str, Any]) -> None:
    """Запустить redmail, если он не запущен. Бинарники — из
    args["candidates"] (см. default_config.yaml), как у launch_app."""
    launch_app({"candidates": args.get("candidates", _DEFAULT_LAUNCH_CANDIDATES)})


def _call(args: dict[str, Any], func, *call_args, **call_kwargs):
    """Вызов функции IPC-клиента с переводом её ошибок в ActionError.

    Если почта не запущена — запускаем её и просим повторить команду:
    старт redmail (Qt + WebEngine) занимает несколько секунд, и держать
    на это цикл прослушивания микрофона было бы хуже, чем попросить
    сказать команду ещё раз."""
    try:
        return func(*call_args, **call_kwargs)
    except RedmailNotRunning as exc:
        _launch_redmail(args)
        raise ActionError("Запускаю почту, повторите команду") from exc
    except RedmailError as exc:
        raise ActionError(_spoken_redmail_error(str(exc))) from exc


# Ответы redmail — свободный текст для человека в GUI; для голоса сводим
# их к фиксированным фразам, для которых есть записи (см.
# feedback._PRERECORDED_PHRASES). Всё, что сюда не попало, озвучится
# общим «Не удалось выполнить команду», а точный текст останется в журнале.
_REDMAIL_ERROR_PHRASES = (
    ("организовали вы сами", "Изменить можно только свою встречу"),
    ("учётной записи", "Почта не настроена"),
    ("не настроена", "Почта не настроена"),
)


def _spoken_redmail_error(message: str) -> str:
    log.info("Ответ redmail: %s", message)
    for marker, phrase in _REDMAIL_ERROR_PHRASES:
        if marker in message:
            return phrase
    return message


def _find_single_event(
    args: dict[str, Any], subject: str, on_date: date_cls, hint_time: tuple[int, int] | None
) -> dict:
    """Ищет ровно одно событие через find_events (тема-подстрока + день).
    Несколько совпадений сужаем по времени, если оно было названо; если
    неоднозначность так и не разрешилась — просим уточнить, а не гадаем,
    какое из событий переносить/отменять."""
    events = _call(args, _redmail_find_events, subject=subject or None, date=on_date.isoformat())
    if not events:
        log.info("Событие не найдено: тема %r, дата %s", subject, on_date.isoformat())
        raise ActionError("Событие не найдено")
    if len(events) > 1 and hint_time is not None:
        narrowed = [event for event in events if _local_hour_minute(event["start"]) == hint_time]
        if narrowed:
            events = narrowed
    if len(events) > 1:
        log.info("Несколько событий по теме %r на %s: %s", subject, on_date.isoformat(), [e["summary"] for e in events])
        raise ActionError("Найдено несколько похожих событий, уточните тему")
    return events[0]


def redmail_focus(args: dict[str, Any]) -> None:
    """"открой почту": окно redmail на передний план, а если почта не
    запущена — запустить её (для человека "открой почту" значит именно
    это, а не "покажи уже открытое окно")."""
    try:
        _redmail_focus()
    except RedmailNotRunning:
        _launch_redmail(args)
    except RedmailError as exc:
        raise ActionError(str(exc)) from exc


def redmail_create_event(args: dict[str, Any]) -> None:
    """"создай встречу <тема> [<дата>] в <время>" — дата не названа, значит
    сегодня; продолжительность здесь всегда час (голосовая длительность
    пока не разбирается — см. ru_datetime), время назвать обязательно,
    иначе непонятно, когда ставить встречу."""
    today = date_cls.today()
    text = str(args.get("remainder", "")).strip()
    subject, on_date, on_time = ru_datetime.extract(text, today=today)
    if not subject:
        raise ActionError("Не расслышала тему события")
    if on_time is None:
        raise ActionError("Не расслышала время события")
    if on_date is None:
        on_date = today
    start = f"{on_date.isoformat()}T{on_time[0]:02d}:{on_time[1]:02d}:00"
    _call(args, _redmail_create_event, subject=subject, start=start, duration_minutes=60)


def redmail_reschedule_event(args: dict[str, Any]) -> None:
    """"перенеси встречу <тема> [<старая дата>] [<старое время>] на
    <новая дата> <новое время>" — обе даты опциональны, обе по умолчанию
    сегодня; новое время назвать обязательно, старое используется только
    чтобы отличить событие, если по теме+дню нашлось несколько."""
    today = date_cls.today()
    text = str(args.get("remainder", "")).strip()
    words = text.split()
    split = _split_on_last_word(words, "на")
    if split is None:
        raise ActionError("Не расслышала, на какое время перенести")
    head_words, tail_words = split

    _leftover, new_date, new_time = ru_datetime.extract(" ".join(tail_words), today=today)
    if new_time is None and new_date is None:
        raise ActionError("Не расслышала, на какое время перенести")
    if new_date is None:
        new_date = today

    subject, old_date, old_time = ru_datetime.extract(" ".join(head_words), today=today)
    if old_date is None:
        old_date = today

    event = _find_single_event(args, subject, old_date, old_time)
    if new_time is None:
        # Названа только дата («на завтра») — время встречи остаётся прежним.
        new_time = _local_hour_minute(event["start"])
    new_start = f"{new_date.isoformat()}T{new_time[0]:02d}:{new_time[1]:02d}:00"
    _call(args, _redmail_update_event, event["uid"], start=new_start)


def redmail_cancel_event(args: dict[str, Any]) -> None:
    """"отмени встречу <тема> [<дата>]" — дата не названа, значит сегодня."""
    today = date_cls.today()
    text = str(args.get("remainder", "")).strip()
    subject, on_date, on_time = ru_datetime.extract(text, today=today)
    if on_date is None:
        on_date = today
    event = _find_single_event(args, subject, on_date, on_time)
    _call(args, _redmail_cancel_event, event["uid"])


# ---------------------------------------------------------------------------
# Пошаговая форма встречи — режим заполнения «на открытом окне»
#
# "вика создай встречу [тема] [дата] [время]" открывает в redmail обычное окно
# встречи (поля из первой фразы уже заполнены) и возвращает FormSession —
# по нему assistant.py переходит в режим заполнения: дальше фразы
# принимаются БЕЗ активационного слова и разбираются handle_form_phrase():
# "тема планёрка", "дата пятнадцатое сентября", "время восемь тридцать",
# "продолжительность два часа", "повторение каждую неделю", "участники
# шилкин пономарёв", "место ...", "описание ...", "сохранить"/"отменить".
# Каждое поле сразу видно в окне; голосом — только записанные фразы, и
# только при ошибке или завершении.
# ---------------------------------------------------------------------------


class FormSession:
    """Маркер результата действия: форма открыта, помощнику пора в режим
    заполнения (assistant.py смотрит на enter_form_mode)."""

    enter_form_mode = True


@dataclass
class FormReply:
    handled: bool  # фраза была про форму (поле / сохранить / отменить)
    spoken: str | None = None  # что озвучить: синтезом — любой текст, записью — фиксированная фраза
    finished: bool = False  # режим заполнения окончен (сохранено/отменено/окно закрыто)
    # Чем озвучить, если движка синтеза нет и для spoken нет записи
    # (например, «Участник Жилкин не найден» -> запись «Участник не найден»).
    spoken_fallback: str | None = None


_PARTICIPANT_FILLERS = ("и", "а", "также", "ещё", "еще")


def _default_form_words() -> EventFormWords:
    """Слова полей из default_config.yaml пакета — когда вызывающая сторона
    не передала свои (тесты, test-command)."""
    from .config import _read_default_config

    return EventFormWords.from_dict(_read_default_config().get("event_form"))


def _keyword_map(words: EventFormWords) -> dict[str, str]:
    """"тема" -> "subject", "пригласить" -> "participants", ... — по словам
    из конфига (GUI, таблица «Форма встречи»)."""
    return {
        keyword.lower(): field
        for field, keywords in words.fields.items()
        for keyword in keywords
        if keyword
    }


def redmail_event_form(args: dict[str, Any]) -> FormSession:
    """"создай встречу [тема] [дата] [время]" -> открыть форму с тем, что
    названо; args["edit"] -> "измени встречу <тема> [дата]": найти свою
    встречу (как у переноса) и открыть её форму."""
    today = date_cls.today()
    text = str(args.get("remainder", "")).strip()
    subject, on_date, on_time = ru_datetime.extract(text, today=today)
    if args.get("edit"):
        event = _find_single_event(args, subject, on_date or today, on_time)
        _call(args, _redmail_event_form_open, uid=event["uid"])
        return FormSession()
    fields: dict[str, Any] = {}
    if subject:
        fields["subject"] = subject
    if on_date is not None:
        fields["date"] = on_date.isoformat()
    if on_time is not None:
        fields["time"] = f"{on_time[0]:02d}:{on_time[1]:02d}"
    _call(args, _redmail_event_form_open, **fields)
    return FormSession()


def _form_closed(exc: RedmailError) -> bool:
    # Именно форма: «Адресная книга не открыта» — другой случай (книгу
    # закрыли мышью), режим заполнения при этом продолжается.
    return isinstance(exc, RedmailNotRunning) or "Форма встречи не открыта" in str(exc)


def _picker_closed(exc: RedmailError) -> bool:
    return "Адресная книга не открыта" in str(exc)


def handle_form_phrase(
    text: str, *, wake_word: str, fuzzy_threshold: int, words: EventFormWords | None = None
) -> FormReply:
    """Одна фраза в режиме заполнения (текст уже нормализован). Активационное
    слово в начале допускается, но не требуется. words — ключевые слова
    полей из конфига (Config.event_form); None — умолчания пакета."""
    form_words = words if words is not None and words.fields else _default_form_words()
    keyword_map = _keyword_map(form_words)
    stripped = strip_wake_word(text, wake_word, fuzzy_threshold)
    if stripped is not None:
        text = stripped
    tokens = text.split()
    if not tokens:
        return FormReply(handled=False)
    first = tokens[0]
    rest_words = tokens[1:]
    rest = " ".join(rest_words)

    if _picker_open:
        reply = handle_picker_phrase(tokens)
        if reply is not None:
            return reply
    listed = _list_participants_command(tokens)
    if listed is not None:
        return listed
    opened = _open_picker_command(tokens)
    if opened is not None:
        return opened

    try:
        if first in form_words.save:
            _redmail_event_form_save()
            return FormReply(handled=True, spoken="Встреча сохранена", finished=True)
        if first in form_words.cancel:
            _redmail_event_form_cancel()
            return FormReply(handled=True, spoken="Отменено", finished=True)

        field = keyword_map.get(first)
        if field is None:
            # Помощник только что спросил «уточните имя» — ответом служит
            # голое имя без слова «участники» («евгений»), если оно
            # выбирает кого-то из запомненных кандидатов.
            if _pending_candidates and _local_matches(tokens, _pending_candidates):
                return _set_participants(tokens)
            return FormReply(handled=False)
        if field == "participants":
            return _set_participants(rest_words)
        if not rest:
            return FormReply(handled=True)  # одно слово "тема" без значения — ждём дальше
        if field == "subject":
            _redmail_event_form_set(subject=rest)
        elif field == "date":
            # «дата пятнадцатое сентября четырнадцать ноль ноль» — дату и,
            # если названо, время (с предлогом «в» или без него).
            leftover, value, at = ru_datetime.extract(rest)
            if value is None:
                return FormReply(handled=True, spoken="Не поняла дату")
            if at is None and leftover:
                at = ru_datetime.parse_time("в " + leftover)
            changes: dict[str, Any] = {"date": value.isoformat()}
            if at is not None:
                changes["time"] = f"{at[0]:02d}:{at[1]:02d}"
            _redmail_event_form_set(**changes)
        elif field == "time":
            # поле называют без предлога ("время восемь тридцать") — разбор
            # ждёт "в/на", подставляем
            value = ru_datetime.parse_time(rest if rest.split()[0] in ("в", "во", "на") else "в " + rest)
            if value is None:
                return FormReply(handled=True, spoken="Не поняла время")
            _redmail_event_form_set(time=f"{value[0]:02d}:{value[1]:02d}")
        elif field == "duration":
            minutes = ru_datetime.parse_duration(rest)
            if minutes is None:
                return FormReply(handled=True, spoken="Не поняла продолжительность")
            _redmail_event_form_set(duration_minutes=minutes)
        elif field == "recurrence":
            value = ru_datetime.parse_recurrence(rest)
            if value is None:
                return FormReply(handled=True, spoken="Не поняла повторение")
            _redmail_event_form_set(recurrence=value)
        elif field == "location":
            _redmail_event_form_set(location=rest)
        elif field == "description":
            _redmail_event_form_set(description=rest)
        return FormReply(handled=True)
    except RedmailError as exc:
        if _form_closed(exc):
            log.info("Форма встречи закрыта (%s) — выхожу из режима заполнения", exc)
            return FormReply(handled=True, finished=True)
        message = str(exc)
        log.info("Ответ redmail в режиме заполнения: %s", message)
        if "прошедшую" in message:
            return FormReply(handled=True, spoken="Нельзя запланировать встречу на прошедшую дату")
        if "позже начала" in message:
            return FormReply(handled=True, spoken="Не поняла время")
        return FormReply(handled=True, spoken="Не удалось выполнить команду")


# --- участники: поиск по адресной книге -------------------------------
#
# Адресная книга большая (тысячи контактов): одна фамилия почти всегда даёт
# нескольких («Пономарев» — восемь), поэтому:
#  * слова фразы группируются в одного человека — для каждой позиции
#    пробуем окно из трёх, двух, одного слова и берём самое длинное, по
#    которому что-то нашлось («шилкин евгений александрович» — один
#    запрос, а не три);
#  * ровно один контакт — добавляем и называем его; несколько — называем
#    кандидатов и просим уточнить, а их список запоминаем: следующее
#    «участники евгений» выбирает уже среди них; ноль — говорим, кого
#    именно не нашли.
# Сравнение слов — та же основа, что в redmail (ipc_server.match_contacts):
# без ё/е-различия и без падежного хвоста; здесь копия для локального
# отбора среди запомненных кандидатов.

_STEM_TAIL = set("аеёийоуыьюя")
_COUNT_WORDS = {2: "двое", 3: "трое", 4: "четверо", 5: "пятеро", 6: "шестеро", 7: "семеро", 8: "восемь", 9: "девять"}
_MAX_LISTED_CANDIDATES = 4
_TOO_MANY_CANDIDATES = 10

#: Кандидаты последней неоднозначности (dict name/email), см. выше.
_pending_candidates: list[dict] = []


def _stem(word: str) -> str:
    stem = word.lower().replace("ё", "е")
    stripped = 0
    while len(stem) > 3 and stripped < 3 and stem[-1] in _STEM_TAIL:
        stem = stem[:-1]
        stripped += 1
    return stem


def _word_matches(query_word: str, name_word: str) -> bool:
    q, w = _stem(query_word), _stem(name_word)
    if not q or not w:
        return False
    if q == w:
        return True
    return min(len(q), len(w)) >= 4 and (q.startswith(w) or w.startswith(q))


def _name_words(contact: dict) -> list[str]:
    words = str(contact.get("name", "")).replace(",", " ").split()
    local = str(contact.get("email", "")).split("@", 1)[0]
    words += [w for w in local.replace(".", " ").replace("_", " ").replace("-", " ").split() if w]
    return words


def _local_matches(query_words: list[str], contacts: list[dict]) -> list[dict]:
    return [c for c in contacts if all(any(_word_matches(q, w) for w in _name_words(c)) for q in query_words)]


def _given_names(contact: dict, query_words: list[str]) -> str:
    """Имя и отчество без той части, что человек уже назвал («Шилкин
    Евгений Александрович» по запросу «шилкин» -> «Евгений Александрович»)."""
    rest = [w for w in str(contact.get("name", "")).split() if not any(_word_matches(q, w) for q in query_words)]
    return " ".join(rest) or str(contact.get("name") or contact.get("email", ""))


def _set_participants(name_words: list[str]) -> FormReply:
    names = [w for w in name_words if w not in _PARTICIPANT_FILLERS]
    if not names:
        return FormReply(handled=True)

    added: list[dict] = []
    # (слова запроса, кандидаты, похожие-ли) — неоднозначные и «похожие»
    # разбираются по одному через книгу на экране, в порядке фразы.
    to_pick: list[tuple[list[str], list[dict], bool]] = []
    missing: list[str] = []
    i = 0
    while i < len(names):
        chosen: tuple[list[str], list[dict]] | None = None
        for length in (3, 2, 1):
            window = names[i : i + length]
            if len(window) < length:
                continue
            contacts = _local_matches(window, _pending_candidates) or _redmail_find_contacts(" ".join(window))
            log.info("Участник %r: найдено контактов %d — %s", " ".join(window), len(contacts), [c.get("name") for c in contacts][:8])
            if contacts:
                chosen = (window, contacts)
                break
        if chosen is None:
            # Точно не нашлось — ищем похожие («бутько» -> Будько): ошибки
            # распознавания в одну-две буквы обычны для фамилий.
            similar = _redmail_find_contacts(names[i], fuzzy=True)[:_TOO_MANY_CANDIDATES]
            log.info("Участник %r: похожих %d — %s", names[i], len(similar), [c.get("name") for c in similar])
            if similar:
                to_pick.append(([names[i]], similar, True))
            else:
                missing.append(names[i])
            i += 1
            continue
        window, contacts = chosen
        i += len(window)
        if len(contacts) == 1:
            added.append(contacts[0])
        else:
            to_pick.append((window, contacts, False))

    _remember_names(added + [c for _window, cs, _fuzzy in to_pick for c in cs])
    if added:
        # Уникальные — молча: они тут же видны в списке под полем, а
        # перечисление вслух после каждой фразы утомляет («много повторений»).
        _redmail_event_form_set(add_participants=[c["email"] for c in added])
    _pending_candidates[:] = [c for _window, cs, _fuzzy in to_pick if len(cs) <= _TOO_MANY_CANDIDATES for c in cs]

    parts: list[str] = []
    for window, contacts, fuzzy in to_pick:
        # Первая неоднозначность — книга на экране прямо сейчас, остальные
        # молча встают в очередь и открываются по одной после «принять».
        if _picker_open:
            _picker_queue.append((window, contacts, fuzzy))
            continue
        described = _open_picker_for(window, contacts, fuzzy=fuzzy)
        if described is not None:
            parts.append(described)
            continue
        who = " ".join(window).capitalize()
        if fuzzy:
            parts.append(f"{who}: точно не нашла, похожие — {', '.join(str(c.get('name', '')) for c in contacts[:_MAX_LISTED_CANDIDATES])}")
        elif len(contacts) > _TOO_MANY_CANDIDATES:
            parts.append(f"{who}: совпадений слишком много, назовите фамилию")
        else:
            parts.append(f"{who}: найдено несколько — {', '.join(_given_names(c, window) for c in contacts[:_MAX_LISTED_CANDIDATES])}. Уточните имя")
    for name in missing:
        parts.append(f"{name.capitalize()} не найден")
    if not parts:
        return FormReply(handled=True)
    fallback = "Участник не найден" if (to_pick or missing) else None
    return FormReply(handled=True, spoken=". ".join(parts), spoken_fallback=fallback)


# --- адресная книга на экране (contact_picker_* в redmail) --------------
#
# Гибрид: когда по фамилии нашлось несколько человек (или слишком много),
# помощник открывает книгу redmail с этим фильтром — строки на экране
# пронумерованы, уже выбранные отмечены. Пока книга открыта, любая фраза —
# ответ ей: «второй», «первый и третий», «евгений», «все», «убери второго»,
# «принять» (ОК — отмеченные попадают в участники), «отмена».

_picker_open = False

_ORDINALS = {
    "первый": 1, "первого": 1, "первую": 1, "первая": 1, "первое": 1,
    "второй": 2, "второго": 2, "вторую": 2, "вторая": 2, "второе": 2,
    "третий": 3, "третьего": 3, "третью": 3, "третья": 3, "третье": 3,
    "четвёртый": 4, "четвертый": 4, "четвёртого": 4, "четвертого": 4, "четвёртую": 4, "четвертую": 4,
    "пятый": 5, "пятого": 5, "пятую": 5,
    "шестой": 6, "шестого": 6, "шестую": 6,
    "седьмой": 7, "седьмого": 7, "седьмую": 7,
    "восьмой": 8, "восьмого": 8, "восьмую": 8,
    "девятый": 9, "девятого": 9, "девятую": 9,
    "десятый": 10, "десятого": 10, "десятую": 10,
}
_PICKER_ACCEPT = ("принять", "принято", "готово", "выбрать", "ок", "окей")
_PICKER_CANCEL = ("отмена", "отменить", "отмени", "закрой", "закрыть")
_PICKER_ALL = ("все", "всех")
_PICKER_UNCHECK = ("убери", "убрать", "сними", "снять", "без")
_PICKER_OPEN_PHRASES = ("открой адресную книгу", "открыть адресную книгу", "адресная книга", "адресную книгу", "покажи адресную книгу")


def picker_is_open() -> bool:
    return _picker_open


def _picker_numbers(tokens: list[str]) -> list[int]:
    numbers: list[int] = []
    for token in tokens:
        if token in _ORDINALS:
            numbers.append(_ORDINALS[token])
        elif token.isdigit():
            numbers.append(int(token))
        else:
            value, _nxt = ru_datetime._number_from_words([token], 0)
            if value:
                numbers.append(value)
    return numbers


#: Неоднозначные фамилии, ждущие своей книги: (слова запроса, кандидаты,
#: похожие-ли). Книга одна за раз — следующая открывается после
#: «принять»/«отмена».
_picker_queue: list[tuple[list[str], list[dict], bool]] = []


def _describe_candidates(who: str, candidates: list[dict], query_words: list[str]) -> str:
    """«Шилкин: двое — первый Александр, второй Евгений Александрович» по
    видимым строкам книги (номера — как на экране). Коротко: фраза
    звучит после каждой неоднозначности, длинная утомляет."""
    count = _COUNT_WORDS.get(len(candidates), str(len(candidates)))
    if len(candidates) > _MAX_LISTED_CANDIDATES:
        return f"{who}: {count}, список на экране"
    listed = ", ".join(
        f"{_ordinal_word(c.get('number', i + 1))} {_given_names(c, query_words)}" for i, c in enumerate(candidates)
    )
    return f"{who}: {count} — {listed}"


def _open_next_picker() -> str | None:
    """Открыть книгу для следующей неоднозначности из очереди; вернуть, что
    сказать, либо None, если очередь пуста."""
    while _picker_queue:
        window, contacts, fuzzy = _picker_queue.pop(0)
        described = _open_picker_for(window, contacts, fuzzy=fuzzy)
        if described is not None:
            return described
    return None


def _ordinal_word(number: int) -> str:
    words = {1: "первый", 2: "второй", 3: "третий", 4: "четвёртый", 5: "пятый", 6: "шестой", 7: "седьмой", 8: "восьмой", 9: "девятый", 10: "десятый"}
    return words.get(number, f"номер {number}")


def _picker_filter_for(window: list[str], contacts: list[dict], fuzzy: bool) -> str:
    """Чем фильтровать книгу: тем, что сказано, а для «похожих» — реальной
    фамилией лучшего совпадения (по услышанному «бутько» книга Будько не
    покажет)."""
    if not fuzzy or not contacts:
        return " ".join(window)
    best = str(contacts[0].get("name", "")).split()
    return best[0] if best else " ".join(window)


def _open_picker_for(window: list[str], contacts: list[dict], *, fuzzy: bool = False) -> str | None:
    """Открыть книгу с фильтром по сказанному; вернуть короткую фразу либо
    None, если книгу открыть не удалось (тогда вызывающий скажет по-старому)."""
    global _picker_open
    who = " ".join(window).capitalize()
    try:
        _redmail_picker_open(_picker_filter_for(window, contacts, fuzzy))
    except RedmailError as exc:
        log.info("Адресную книгу открыть не удалось (%s) — отвечаю списком", exc)
        return None
    _picker_open = True
    if fuzzy:
        return f"{who}: точно не нашла, похожие на экране — выберите номер и скажите принять"
    return f"{who}: найдено несколько — выберите номер и скажите принять"


def _picker_select_tokens(tokens: list[str]) -> str | None:
    """Отметить/снять строки по словам фразы («второй», «первый и третий»,
    «евгений», «все», «убери второго»). Возвращает, что сказать при
    неудаче, либо None, если всё отмечено (тогда — только сигнал)."""
    if not tokens:
        return None
    uncheck = tokens[0] in _PICKER_UNCHECK
    rest = tokens[1:] if uncheck else tokens
    if any(t in _PICKER_ALL for t in rest):
        _redmail_picker_select(all_visible=True, checked=not uncheck)
        return None
    numbers = _picker_numbers([t for t in rest if t not in ("и", "номер", "номера")])
    if numbers:
        touched = 0
        for number in numbers:
            touched += int(_redmail_picker_select(number=number, checked=not uncheck).get("touched", 0))
        return None if touched else "Такого номера в списке нет"
    query_words = [t for t in rest if t not in _PARTICIPANT_FILLERS]
    if not query_words:
        return None
    state = _redmail_picker_select(query=" ".join(query_words), checked=not uncheck)
    if int(state.get("touched", 0)) == 0:
        return f"{' '.join(query_words).capitalize()}: в списке нет"
    return None


def _picker_finish(spoken: str | None) -> FormReply:
    """После «принять»/«отмена»: закрыть эту книгу и, если в очереди есть
    следующая неоднозначная фамилия, сразу открыть книгу для неё. После
    «принять» — молча (только сигнал): выбранные видны в списке под
    полем, перечисление — по «назови участников»."""
    global _picker_open
    _picker_open = False
    _pending_candidates.clear()
    following = _open_next_picker()
    if following:
        spoken = f"{spoken}. {following}" if spoken else following
    return FormReply(handled=True, spoken=spoken)


def handle_picker_phrase(tokens: list[str]) -> FormReply | None:
    """Фраза, пока адресная книга открыта. None — книги на экране уже нет
    (закрыли мышью): вызывающий разбирает фразу как обычную."""
    global _picker_open
    if not tokens:
        return FormReply(handled=False)
    try:
        # «два принять» одной фразой: сначала отметить, потом принять.
        accept = tokens[-1] in _PICKER_ACCEPT
        selection = tokens[:-1] if accept else tokens
        if not accept and tokens[0] in _PICKER_CANCEL:
            _redmail_picker_cancel()
            return _picker_finish("Отмена")
        problem = _picker_select_tokens(selection) if selection else None
        if problem and not accept:
            return FormReply(handled=True, spoken=problem)
        if not accept:
            return FormReply(handled=True)
        selected = _redmail_picker_accept()
        _remember_names(selected)
        return _picker_finish(None if selected else "Никто не выбран")
    except RedmailError as exc:
        log.info("Адресная книга: %s", exc)
        _picker_open = False
        if _form_closed(exc):
            return FormReply(handled=True, finished=True)
        if _picker_closed(exc):
            _picker_queue.clear()
            return None  # книгу закрыли мышью — фраза относится к форме
        return FormReply(handled=True, spoken="Не удалось выполнить команду")


#: Имена по адресам — всё, что помощник узнал из адресной книги за сеанс
#: (найденные, выбранные в книге). Нужно для «назови участников»: форма
#: отдаёт только адреса.
_known_names: dict[str, str] = {}

_LIST_PHRASES = ("назови участников", "перечисли участников", "кто участники", "какие участники", "список участников", "кто приглашён", "кого пригласили")


def _remember_names(contacts: list[dict]) -> None:
    for contact in contacts:
        email = str(contact.get("email", "")).casefold()
        name = str(contact.get("name", "")).strip()
        if email and name:
            _known_names[email] = name


def _name_for(email: str) -> str:
    """Имя по адресу: из запомненных, иначе — спросить книгу по локальной
    части адреса (redmail сравнивает и её), иначе — сам адрес."""
    key = email.casefold()
    if key in _known_names:
        return _known_names[key]
    local = email.split("@", 1)[0]
    try:
        found = [c for c in _redmail_find_contacts(local) if str(c.get("email", "")).casefold() == key]
    except RedmailError:
        found = []
    if found:
        _remember_names(found)
        return _known_names[key]
    return email


def _list_participants_command(tokens: list[str]) -> FormReply | None:
    """«назови участников» — перечислить, кто сейчас в форме."""
    text = " ".join(tokens)
    if not any(text.startswith(phrase) for phrase in _LIST_PHRASES):
        return None
    try:
        state = _redmail_event_form_state()
    except RedmailError as exc:
        if _form_closed(exc):
            return FormReply(handled=True, finished=True)
        return FormReply(handled=True, spoken="Не удалось выполнить команду")
    emails = [e for e in state.get("participants", []) if isinstance(e, str)]
    if not emails:
        return FormReply(handled=True, spoken="Участников пока нет")
    names = ", ".join(_name_for(e) for e in emails)
    count = _COUNT_WORDS.get(len(emails), str(len(emails)))
    return FormReply(handled=True, spoken=f"Участники — {count}: {names}" if len(emails) > 1 else f"Участник: {names}")


def _open_picker_command(tokens: list[str]) -> FormReply | None:
    """«открой адресную книгу [фильтр]» в режиме заполнения."""
    global _picker_open
    text = " ".join(tokens)
    for phrase in _PICKER_OPEN_PHRASES:
        if text.startswith(phrase):
            query = text[len(phrase):].strip()
            try:
                state = _redmail_picker_open(query)
            except RedmailError as exc:
                if _form_closed(exc):
                    return FormReply(handled=True, finished=True)
                return FormReply(handled=True, spoken="Не удалось открыть адресную книгу")
            _picker_open = True
            count = len(state.get("candidates", []))
            return FormReply(handled=True, spoken=f"Адресная книга открыта, в списке {count} — выберите номер и скажите принять")
    return None


def looks_like_form_phrase(text: str, *, wake_word: str, fuzzy_threshold: int, words: EventFormWords | None = None) -> bool:
    """Начинается ли фраза со слова-поля или «сохранить»/«отменить» — чтобы в
    режиме ожидания понять, что человек продолжает заполнять открытую форму."""
    form_words = words if words is not None and words.fields else _default_form_words()
    stripped = strip_wake_word(text, wake_word, fuzzy_threshold)
    tokens = (stripped if stripped is not None else text).split()
    if not tokens:
        return False
    if _picker_open:
        return True  # книга на экране — любая фраза адресована ей
    joined = " ".join(tokens)
    if any(joined.startswith(p) for p in _LIST_PHRASES + _PICKER_OPEN_PHRASES):
        return True
    if tokens[0] in _keyword_map(form_words) or tokens[0] in form_words.save or tokens[0] in form_words.cancel:
        return True
    # ответ на «уточните имя» — голое имя из запомненных кандидатов
    return bool(_pending_candidates) and bool(_local_matches(tokens, _pending_candidates))


def form_is_open() -> bool:
    """Открыта ли сейчас форма встречи в redmail."""
    try:
        _redmail_event_form_state()
    except RedmailError:
        return False
    return True


def redmail_event_form_resume(args: dict[str, Any]) -> FormSession:  # noqa: ARG001
    """"продолжи настраивать встречу": вернуться в режим заполнения, если окно
    встречи в redmail ещё открыто (режим мог погаснуть по таймауту, пока
    человек переключался между окнами)."""
    if not form_is_open():
        raise ActionError("Окно встречи не открыто")
    return FormSession()


ACTIONS = {
    "redmail_focus": redmail_focus,
    "redmail_event_form_resume": redmail_event_form_resume,
    # Старое имя действия "создай встречу" — теперь это та же пошаговая
    # форма: конфиги, сохранённые из GUI до появления формы, продолжают
    # работать (и получают режим заполнения), а не просят назвать тему.
    "redmail_create_event": redmail_event_form,
    "redmail_event_form": redmail_event_form,
    "redmail_reschedule_event": redmail_reschedule_event,
    "redmail_cancel_event": redmail_cancel_event,
}
