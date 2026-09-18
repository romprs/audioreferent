"""Приём просьб произнести текст (сокет помощника).

Кто просит: резидент напоминаний почтового клиента (redmail-reminder) —
встреча начинается, и человек просил напомнить голосом. Собственного
расписания у помощника нет и не нужно: календарь один, и живёт он в почте.

Канал намеренно односторонний и крошечный: строка JSON на запрос, ответа
не ждём. Слушаем unix-сокет в каталоге текущего сеанса ($XDG_RUNTIME_DIR),
то есть достучаться может только тот же пользователь на этой же машине.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

SOCKET_ENV = "AUDIOREFERENT_SOCKET"
SOCKET_NAME = "audioreferent.sock"

#: Больше одной фразы за раз не бывает; ограничение защищает от того, что
#: в сокет напишут поток данных вместо строки.
MAX_REQUEST_BYTES = 8192

#: Сколько текста произносим: длинная фраза — это ошибка на стороне
#: просящего, а не осмысленное напоминание.
MAX_TEXT_CHARS = 300


def socket_path() -> Path:
    """Каталог сеанса ($XDG_RUNTIME_DIR, права 0700) — обычное место для
    таких сокетов. Если его нет, кладём в СВОЙ каталог внутри /tmp с
    правами 0700: сам /tmp доступен всем на запись, и сокет в его корне
    мог бы дёргать любой другой пользователь машины."""
    override = os.environ.get(SOCKET_ENV)
    if override:
        return Path(override)
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / SOCKET_NAME
    return Path("/tmp") / f"audioreferent-{os.getuid()}" / SOCKET_NAME


class SpeakListener:
    """Слушает сокет и зовёт speak(text) для каждой просьбы.

    speak вызывается в потоке слушателя, поэтому в помощнике он должен быть
    безопасен для вызова извне главного цикла (см. Assistant.speak_external).
    """

    def __init__(self, speak: Callable[[str], None], path: Path | None = None) -> None:
        self._speak = speak
        self._path = path or socket_path()
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> bool:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self._path.is_socket() or self._path.exists():
                self._path.unlink()  # сокет прошлого запуска, слушать его некому
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            # Права ставим МАСКОЙ до bind, а не chmod после: между bind и
            # chmod сокет существовал бы с правами по umask, и в этот
            # промежуток к нему мог подключиться посторонний. Темы встреч
            # чужим слышать незачем.
            previous_umask = os.umask(0o177)
            try:
                server.bind(str(self._path))
            finally:
                os.umask(previous_umask)
            os.chmod(self._path, 0o600)
            # Очередь с запасом: несколько напоминаний могут прийти подряд,
            # а переполненная очередь даёт просящему EAGAIN вместо доставки.
            server.listen(16)
            server.settimeout(0.5)
        except OSError as exc:
            log.warning("Канал помощника не поднят (%s): %s", self._path, exc)
            return False
        self._server = server
        self._thread = threading.Thread(target=self._serve, name="speak-listener", daemon=True)
        self._thread.start()
        log.info("Канал помощника слушает %s", self._path)
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)
        try:
            self._path.unlink()
        except OSError:
            pass

    def _serve(self) -> None:
        assert self._server is not None
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(2.0)
                try:
                    self._handle(conn.recv(MAX_REQUEST_BYTES))
                except OSError as exc:
                    log.info("Канал помощника: запрос не прочитан: %s", exc)

    def _handle(self, raw: bytes) -> None:
        text = parse_speak_request(raw)
        if text is None:
            return
        log.info("Канал помощника: произнести %r", text)
        try:
            self._speak(text)
        except Exception as exc:  # ошибка синтеза не должна ронять поток слушателя
            log.warning("Канал помощника: не удалось произнести: %s", exc)


def parse_speak_request(raw: bytes) -> str | None:
    """Текст из запроса или None, если запрос не наш/битый. Содержимое
    приходит извне, поэтому проверяем всё: и структуру, и длину."""
    try:
        request = json.loads(raw.decode("utf-8").strip() or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        log.info("Канал помощника: запрос не разобран")
        return None
    if not isinstance(request, dict) or request.get("action") != "speak":
        return None
    args = request.get("args")
    text = args.get("text") if isinstance(args, dict) else None
    if not isinstance(text, str):
        return None
    # Переводы строк убираем: синтез читает их как паузы, а в напоминании
    # им взяться неоткуда, кроме как из темы встречи.
    text = " ".join(text.split())
    return text[:MAX_TEXT_CHARS] if text else None
