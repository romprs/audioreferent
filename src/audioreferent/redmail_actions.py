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
from .actions import ActionError, launch_app
from .redmail_client import RedmailError, RedmailNotRunning
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


ACTIONS = {
    "redmail_focus": redmail_focus,
    "redmail_create_event": redmail_create_event,
    "redmail_reschedule_event": redmail_reschedule_event,
    "redmail_cancel_event": redmail_cancel_event,
}
