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
from .redmail_client import RedmailError, RedmailNotRunning
from .redmail_client import cancel_event as _redmail_cancel_event
from .redmail_client import create_event as _redmail_create_event
from .redmail_client import event_form_cancel as _redmail_event_form_cancel
from .redmail_client import event_form_open as _redmail_event_form_open
from .redmail_client import event_form_save as _redmail_event_form_save
from .redmail_client import event_form_set as _redmail_event_form_set
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
    if new_time is None:
        raise ActionError("Не расслышала, на какое время перенести")
    if new_date is None:
        new_date = today

    subject, old_date, old_time = ru_datetime.extract(" ".join(head_words), today=today)
    if old_date is None:
        old_date = today

    event = _find_single_event(args, subject, old_date, old_time)
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
    spoken: str | None = None  # что озвучить (фиксированная фраза с записью) либо ничего
    finished: bool = False  # режим заполнения окончен (сохранено/отменено/окно закрыто)


_FIELD_KEYWORDS = {
    "тема": "subject",
    "название": "subject",
    "дата": "date",
    "число": "date",
    "время": "time",
    "начало": "time",
    "продолжительность": "duration",
    "длительность": "duration",
    "повторение": "recurrence",
    "повторять": "recurrence",
    "повтор": "recurrence",
    "участники": "participants",
    "участник": "participants",
    "пригласить": "participants",
    "пригласи": "participants",
    "место": "location",
    "описание": "description",
}
_SAVE_WORDS = ("сохранить", "сохрани")
_CANCEL_WORDS = ("отменить", "отмени", "отмена")
_PARTICIPANT_FILLERS = ("и", "а", "также", "ещё", "еще")


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
    return isinstance(exc, RedmailNotRunning) or "не открыта" in str(exc)


def handle_form_phrase(text: str, *, wake_word: str, fuzzy_threshold: int) -> FormReply:
    """Одна фраза в режиме заполнения (текст уже нормализован). Активационное
    слово в начале допускается, но не требуется."""
    stripped = strip_wake_word(text, wake_word, fuzzy_threshold)
    if stripped is not None:
        text = stripped
    words = text.split()
    if not words:
        return FormReply(handled=False)
    first = words[0]
    rest_words = words[1:]
    rest = " ".join(rest_words)

    try:
        if first in _SAVE_WORDS:
            _redmail_event_form_save()
            return FormReply(handled=True, spoken="Встреча сохранена", finished=True)
        if first in _CANCEL_WORDS:
            _redmail_event_form_cancel()
            return FormReply(handled=True, spoken="Отменено", finished=True)

        field = _FIELD_KEYWORDS.get(first)
        if field is None:
            return FormReply(handled=False)
        if field == "participants":
            return _set_participants(rest_words)
        if not rest:
            return FormReply(handled=True)  # одно слово "тема" без значения — ждём дальше
        if field == "subject":
            _redmail_event_form_set(subject=rest)
        elif field == "date":
            value = ru_datetime.parse_date(rest)
            if value is None:
                return FormReply(handled=True, spoken="Не поняла дату")
            _redmail_event_form_set(date=value.isoformat())
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


def _set_participants(name_words: list[str]) -> FormReply:
    """"участники шилкин пономарёв будько": каждое слово — фамилия (или имя),
    ищется в адресной книге redmail по основе слова. Ровно один контакт —
    добавляем; ноль или несколько — «Участник не найден» (кто именно — в
    журнале), остальных всё равно добавляем."""
    names = [w for w in name_words if w not in _PARTICIPANT_FILLERS]
    if not names:
        return FormReply(handled=True)
    emails: list[str] = []
    missing: list[str] = []
    for name in names:
        contacts = _redmail_find_contacts(name)
        if len(contacts) == 1:
            emails.append(contacts[0]["email"])
        else:
            missing.append(name)
            log.info("Участник %r: найдено контактов %d — %s", name, len(contacts), [c.get("name") for c in contacts])
    if emails:
        _redmail_event_form_set(add_participants=emails)
    return FormReply(handled=True, spoken="Участник не найден" if missing else None)


ACTIONS = {
    "redmail_focus": redmail_focus,
    "redmail_create_event": redmail_create_event,
    "redmail_event_form": redmail_event_form,
    "redmail_reschedule_event": redmail_reschedule_event,
    "redmail_cancel_event": redmail_cancel_event,
}
