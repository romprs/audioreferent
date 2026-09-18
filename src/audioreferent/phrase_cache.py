"""Кэш синтезированных фраз на диске.

Зачем: синтез одной фразы на слабой или загруженной машине занимает
секунды (замер на рабочей станции: 2 с на «Отменено», 6 с на длинную
подсказку), и ждать этого при каждом ответе нельзя. Фразы у помощника
повторяются — фиксированные ответы всегда одни и те же, фамилии
сотрудников повторяются изо дня в день, — поэтому достаточно синтезировать
каждую один раз.

Кэш переживает перезапуск сервиса: файлы лежат в
~/.cache/audioreferent/tts/<движок>/<голос>/<хэш текста>.pcm (сырой PCM16
той частоты, с которой работает движок — конвертировать при
воспроизведении не нужно). Ключ включает движок, голос и скорость речи:
сменив голос, старые записи не подхватим по ошибке.

Готовые фразы из пакета (см. prebuilt_dir) кладутся туда же при сборке
RPM — тогда фиксированные ответы не синтезируются на рабочей машине
вообще ни разу.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

#: Куда пакет кладёт заранее синтезированные фразы (создаётся при сборке).
PREBUILT_DIR = Path("/usr/share/audioreferent/tts-cache")


def cache_root() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return base / "audioreferent" / "tts"


def key_for(text: str, *, engine: str, voice: str, rate: float) -> str:
    """Хэш текста вместе с параметрами голоса — чтобы после смены голоса
    или скорости зазвучало новое, а не старое из кэша."""
    payload = f"{engine}|{voice}|{rate:.2f}|{text}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()  # noqa: S324 — не криптография, просто имя файла


class PhraseCache:
    """PCM16 по тексту: сначала из пакета, потом из пользовательского
    кэша, иначе — синтез (его выполняет вызывающий) и запись на диск.

    Любая ошибка файловой системы не должна мешать говорить: кэш в этом
    случае просто не работает, о чём пишем в журнал один раз."""

    def __init__(self, engine: str, voice: str, rate: float, *, prebuilt_dir: Path | None = None):
        self.engine = engine
        self.voice = voice
        self.rate = rate
        self._dir = cache_root() / engine / voice
        self._prebuilt = (prebuilt_dir if prebuilt_dir is not None else PREBUILT_DIR) / engine / voice
        self._broken = False

    def _paths(self, text: str) -> tuple[Path, Path]:
        name = key_for(text, engine=self.engine, voice=self.voice, rate=self.rate) + ".pcm"
        return self._prebuilt / name, self._dir / name

    def get(self, text: str) -> bytes | None:
        prebuilt, cached = self._paths(text)
        for path in (prebuilt, cached):
            try:
                if path.is_file():
                    return path.read_bytes()
            except OSError as exc:
                log.debug("Кэш фраз: не прочитать %s (%s)", path, exc)
        return None

    def put(self, text: str, pcm: bytes) -> None:
        if self._broken or not pcm:
            return
        _prebuilt, cached = self._paths(text)
        try:
            cached.parent.mkdir(parents=True, exist_ok=True)
            # Через временный файл: иначе при выключении питания на диске
            # останется обрезанная фраза, и она будет «проигрываться» вечно.
            with tempfile.NamedTemporaryFile(dir=cached.parent, delete=False) as tmp:
                tmp.write(pcm)
                temp_path = Path(tmp.name)
            temp_path.replace(cached)
        except OSError as exc:
            self._broken = True
            log.warning("Кэш фраз не работает (%s) — синтез будет каждый раз", exc)
