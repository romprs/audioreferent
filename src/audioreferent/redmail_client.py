"""Клиент локального канала управления почтовым клиентом redmail (см.
ipc_server.py в соседнем проекте romprs/redmail) — позволяет голосовым
командам открывать в redmail письмо/встречу с уже заполненными полями.

Транспорт зеркалит сервер: построчный JSON поверх unix-сокета. Путь самого
сокета — деталь ОС (зависит от $XDG_RUNTIME_DIR), поэтому не угадывается, а
читается из ~/.config/redmail/ipc-endpoint.json, куда его при запуске
публикует redmail (redmail.ipc_server.endpoint_file_path()).

Важно: ничего из отправляемого наружу (письмо, приглашение, отмена/перенос
встречи) не уходит без экранного подтверждения — команды redmail лишь
открывают обычный диалог с заполненными полями, кнопку "Отправить"/
"Сохранить"/"Да" всё равно нажимает человек. Эта гарантия — на стороне
redmail (ipc_server.py) и здесь не может быть ослаблена ни при каких
аргументах.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any

_TIMEOUT_SECONDS = 5.0


class RedmailError(Exception):
    """Не получилось поговорить с redmail: не запущен, канал не поднят,
    либо сама команда на его стороне вернула ошибку (например, "Встреча с
    UID ... не найдена"). Для вызывающего кода это "не получилось";
    единственный случай, который он различает отдельно — RedmailNotRunning."""


class RedmailNotRunning(RedmailError):
    """redmail не запущен вовсе (нет файла адреса канала — redmail пишет
    его при старте и убирает при выходе). Отдельный класс, потому что на
    это есть осмысленная реакция — запустить почту, — а на прочие ошибки
    связи нет."""


def _redmail_config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "redmail"


def _endpoint_address() -> str:
    endpoint_file = _redmail_config_dir() / "ipc-endpoint.json"
    try:
        data = json.loads(endpoint_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RedmailNotRunning("Почта не запущена") from exc
    value = data.get("full_server_name")
    if not isinstance(value, str) or not value:
        raise RedmailNotRunning("Почта не запущена")
    return value


def send_request(action: str, args: dict[str, Any] | None = None) -> dict:
    """Один запрос -> один разобранный ответ. RedmailError и на сбое связи,
    и когда сама команда ответила {"ok": false, ...}."""
    endpoint = _endpoint_address()
    request = {"action": action, "args": args or {}}
    try:
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(_TIMEOUT_SECONDS)
        conn.connect(endpoint)
    except (ConnectionRefusedError, FileNotFoundError) as exc:
        # Файл адреса есть, а слушать некому: redmail умер, не успев его
        # убрать (крах, SIGKILL — например, при перезапуске сервиса, из
        # которого его запустили). Для нас это то же «почта не запущена» —
        # запускать её; свой устаревший сокет redmail при старте уберёт сам.
        raise RedmailNotRunning("Почта не запущена") from exc
    except OSError as exc:
        raise RedmailError("Не удалось подключиться к почте") from exc
    try:
        conn.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
        buffer = b""
        while b"\n" not in buffer:
            chunk = conn.recv(65536)
            if not chunk:
                raise RedmailError("Почта закрыла соединение без ответа")
            buffer += chunk
    finally:
        conn.close()
    response = json.loads(buffer.split(b"\n", 1)[0].decode("utf-8"))
    if not response.get("ok"):
        raise RedmailError(response.get("error") or "Почта сообщила об ошибке")
    return response


def focus(section: str | None = None) -> None:
    """Окно почты на передний план; section — mail, calendar или contacts."""
    send_request("focus", {"section": section} if section else {})


def compose_email(*, to: str, subject: str = "", body: str = "", cc: str = "", bcc: str = "") -> None:
    send_request(
        "compose_email",
        {"to": to, "subject": subject, "body": body, "cc": cc, "bcc": bcc},
    )


def create_event(
    *,
    subject: str,
    start: str,
    duration_minutes: int = 60,
    participants: list[str] | None = None,
    description: str = "",
    location: str = "",
) -> None:
    send_request(
        "create_event",
        {
            "subject": subject,
            "start": start,
            "duration_minutes": duration_minutes,
            "participants": participants or [],
            "description": description,
            "location": location,
        },
    )


def update_event(uid: str, **changes: Any) -> None:
    send_request("update_event", {"uid": uid, **changes})


def cancel_event(
    uid: str, *, occurrence_start: str | None = None, scope: str | None = None, confirmed: bool = False
) -> None:
    """confirmed=True — отменить сразу, без окна подтверждения в почте
    (помощник уже спросил голосом). occurrence_start — какой день серии
    (start из find_events), scope — one (только этот день) или all (серия)."""
    args: dict[str, Any] = {"uid": uid}
    if occurrence_start:
        args["occurrence_start"] = occurrence_start
    if scope:
        args["scope"] = scope
    if confirmed:
        args["confirmed"] = True
    send_request("cancel_event", args)


# --- пошаговая форма встречи (event_form_* в redmail/ipc_server.py) ---
#
# Поля: subject, date (YYYY-MM-DD), time (HH:MM), start (ISO), duration_minutes,
# recurrence (none/daily/weekly/monthly/yearly), participants / add_participants
# (адреса), location, description, all_day. Открытая форма — обычное окно
# встречи redmail на экране; «Сохранить»/«Отмена» нажимают event_form_save/
# event_form_cancel, и сохранение идёт тем же путём, что и кнопка в окне.


def event_form_open(*, uid: str | None = None, **fields: Any) -> dict:
    args: dict[str, Any] = dict(fields)
    if uid:
        args["uid"] = uid
    return send_request("event_form_open", args).get("form", {})


def event_form_set(**fields: Any) -> dict:
    return send_request("event_form_set", fields).get("form", {})


def event_form_state() -> dict:
    return send_request("event_form_state").get("form", {})


def event_form_save() -> dict:
    return send_request("event_form_save").get("form", {})


def event_form_cancel() -> None:
    send_request("event_form_cancel")


def event_form_focus(field: str) -> dict:
    """Подсветить в окне поле, о котором помощник сейчас спрашивает."""
    return send_request("event_form_focus", {"field": field}).get("form", {})


def list_calendars() -> list[dict]:
    """Календари redmail по порядку: [{number, id, name, source, current}]."""
    calendars = send_request("list_calendars").get("calendars", [])
    return [c for c in calendars if isinstance(c, dict)]


# --- адресная книга поверх открытой формы (contact_picker_* в redmail) ---


def contact_picker_open(query: str = "") -> dict:
    """Открыть книгу с фильтром; ответ — {"query", "candidates": [{number,
    name, email, checked}]} для видимых строк."""
    return send_request("contact_picker_open", {"query": query}).get("picker", {})


def contact_picker_select(
    *, number: int | None = None, query: str | None = None, all_visible: bool = False, checked: bool = True
) -> dict:
    args: dict[str, Any] = {"checked": checked}
    if number is not None:
        args["number"] = number
    if query:
        args["query"] = query
    if all_visible:
        args["all"] = True
    return send_request("contact_picker_select", args).get("picker", {})


def contact_picker_state() -> dict:
    return send_request("contact_picker_state").get("picker", {})


def contact_picker_accept() -> list[dict]:
    selected = send_request("contact_picker_accept").get("selected", [])
    return selected if isinstance(selected, list) else []


def contact_picker_cancel() -> None:
    send_request("contact_picker_cancel")


def find_contacts(query: str, *, fuzzy: bool = False) -> list[dict]:
    """Контакты адресной книги по фамилии/имени, как их слышно в речи
    (redmail сам сравнивает основы слов: «Шилкина» -> Шилкин). fuzzy —
    с допуском на 1-2 ошибки распознавания («бутько» -> Будько), от самых
    похожих."""
    args: dict[str, Any] = {"query": query}
    if fuzzy:
        args["fuzzy"] = True
    contacts = send_request("find_contacts", args).get("contacts", [])
    return contacts if isinstance(contacts, list) else []


def find_events(*, subject: str | None = None, date: str | None = None) -> list[dict]:
    args: dict[str, Any] = {}
    if subject:
        args["subject"] = subject
    if date:
        args["date"] = date
    response = send_request("find_events", args)
    events = response.get("events", [])
    return events if isinstance(events, list) else []
