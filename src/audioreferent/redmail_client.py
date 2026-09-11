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


def focus() -> None:
    send_request("focus")


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


def cancel_event(uid: str) -> None:
    send_request("cancel_event", {"uid": uid})


def find_events(*, subject: str | None = None, date: str | None = None) -> list[dict]:
    args: dict[str, Any] = {}
    if subject:
        args["subject"] = subject
    if date:
        args["date"] = date
    response = send_request("find_events", args)
    events = response.get("events", [])
    return events if isinstance(events, list) else []
