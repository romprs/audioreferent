from __future__ import annotations

import json
import socket
import time
from pathlib import Path

from audioreferent import ipc_listener


def _send(path: Path, payload: object) -> None:
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(2)
    conn.connect(str(path))
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    conn.sendall(raw + b"\n")
    conn.close()


def _wait_for(spoken: list[str], count: int = 1, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and len(spoken) < count:
        time.sleep(0.05)


def test_listener_speaks_requested_text(tmp_path: Path) -> None:
    spoken: list[str] = []
    listener = ipc_listener.SpeakListener(spoken.append, tmp_path / "s.sock")
    assert listener.start()
    try:
        _send(tmp_path / "s.sock", {"action": "speak", "args": {"text": "Напоминание: планёрка через 15 минут"}})
        _wait_for(spoken)
    finally:
        listener.stop()
    assert spoken == ["Напоминание: планёрка через 15 минут"]


def test_listener_ignores_foreign_and_broken_requests(tmp_path: Path) -> None:
    """В сокет может прийти что угодно — молчим, а не падаем и не
    произносим мусор."""
    spoken: list[str] = []
    listener = ipc_listener.SpeakListener(spoken.append, tmp_path / "s.sock")
    assert listener.start()
    try:
        for payload in (b"not json at all", b"[]", {"action": "shutdown"}, {"action": "speak"},
                        {"action": "speak", "args": {"text": 42}}, {"action": "speak", "args": {"text": "   "}}):
            _send(tmp_path / "s.sock", payload)
        time.sleep(0.5)
        _send(tmp_path / "s.sock", {"action": "speak", "args": {"text": "живой"}})
        _wait_for(spoken)
    finally:
        listener.stop()
    assert spoken == ["живой"]


def test_speak_request_is_trimmed_and_limited() -> None:
    long_text = "а" * (ipc_listener.MAX_TEXT_CHARS + 500)
    parsed = ipc_listener.parse_speak_request(
        json.dumps({"action": "speak", "args": {"text": long_text}}).encode("utf-8")
    )
    assert parsed is not None and len(parsed) == ipc_listener.MAX_TEXT_CHARS

    multiline = ipc_listener.parse_speak_request(
        json.dumps({"action": "speak", "args": {"text": "Планёрка\n\nв 10:00"}}).encode("utf-8")
    )
    assert multiline == "Планёрка в 10:00"


def test_socket_is_private_to_owner(tmp_path: Path) -> None:
    """Темы встреч — не для соседей по машине: сокет доступен только
    владельцу."""
    listener = ipc_listener.SpeakListener(lambda _text: None, tmp_path / "s.sock")
    assert listener.start()
    try:
        assert (tmp_path / "s.sock").stat().st_mode & 0o777 == 0o600
    finally:
        listener.stop()


def test_stale_socket_file_does_not_block_start(tmp_path: Path) -> None:
    path = tmp_path / "s.sock"
    path.write_text("", encoding="utf-8")  # остался от прошлого запуска
    listener = ipc_listener.SpeakListener(lambda _text: None, path)
    assert listener.start()
    listener.stop()
