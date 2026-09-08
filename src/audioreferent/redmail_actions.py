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

from . import ru_datetime
from .actions import ActionError
from .redmail_client import RedmailError
from .redmail_client import cancel_event as _redmail_cancel_event
from .redmail_client import create_event as _redmail_create_event
from .redmail_client import find_events as _redmail_find_events
from .redmail_client import focus as _redmail_focus
from .redmail_client import update_event as _redmail_update_event

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


def _find_single_event(subject: str, on_date: date_cls, hint_time: tuple[int, int] | None) -> dict:
    """Ищет ровно одно событие через find_events (тема-подстрока + день).
    Несколько совпадений сужаем по времени, если оно было названо; если
    неоднозначность так и не разрешилась — просим уточнить, а не гадаем,
    какое из событий переносить/отменять."""
    try:
        events = _redmail_find_events(subject=subject or None, date=on_date.isoformat())
    except RedmailError as exc:
        raise ActionError(str(exc)) from exc
    if not events:
        label = f"«{subject}»" if subject else "на эту дату"
        raise ActionError(f"Событие {label} не найдено")
    if len(events) > 1 and hint_time is not None:
        narrowed = [event for event in events if _local_hour_minute(event["start"]) == hint_time]
        if narrowed:
            events = narrowed
    if len(events) > 1:
        raise ActionError("Найдено несколько подходящих событий, уточните тему")
    return events[0]


def redmail_focus(args: dict[str, Any]) -> None:  # noqa: ARG001
    try:
        _redmail_focus()
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
    try:
        _redmail_create_event(subject=subject, start=start, duration_minutes=60)
    except RedmailError as exc:
        raise ActionError(str(exc)) from exc


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
        raise ActionError("Не расслышала, на какую дату и время перенести")
    head_words, tail_words = split

    _leftover, new_date, new_time = ru_datetime.extract(" ".join(tail_words), today=today)
    if new_time is None:
        raise ActionError("Не расслышала время, на которое перенести")
    if new_date is None:
        new_date = today

    subject, old_date, old_time = ru_datetime.extract(" ".join(head_words), today=today)
    if old_date is None:
        old_date = today

    event = _find_single_event(subject, old_date, old_time)
    new_start = f"{new_date.isoformat()}T{new_time[0]:02d}:{new_time[1]:02d}:00"
    try:
        _redmail_update_event(event["uid"], start=new_start)
    except RedmailError as exc:
        raise ActionError(str(exc)) from exc


def redmail_cancel_event(args: dict[str, Any]) -> None:
    """"отмени встречу <тема> [<дата>]" — дата не названа, значит сегодня."""
    today = date_cls.today()
    text = str(args.get("remainder", "")).strip()
    subject, on_date, on_time = ru_datetime.extract(text, today=today)
    if on_date is None:
        on_date = today
    event = _find_single_event(subject, on_date, on_time)
    try:
        _redmail_cancel_event(event["uid"])
    except RedmailError as exc:
        raise ActionError(str(exc)) from exc


ACTIONS = {
    "redmail_focus": redmail_focus,
    "redmail_create_event": redmail_create_event,
    "redmail_reschedule_event": redmail_reschedule_event,
    "redmail_cancel_event": redmail_cancel_event,
}
