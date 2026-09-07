"""Звуковая/голосовая обратная связь пользователю."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from importlib import resources

log = logging.getLogger(__name__)

_SOUND_CANDIDATES = [
    "/usr/share/sounds/freedesktop/stereo/message.oga",
    "/usr/share/sounds/freedesktop/stereo/complete.oga",
]

# Заранее записанные фразы (женский голос, сгенерированы офлайн один раз —
# синтез espeak-ng в реальном времени звучит заметно грубее и хуже
# разборчив). Для остальных фраз, которых здесь нет, используется
# espeak-ng как раньше — так что даже без этих записей ничего не ломается.
_PRERECORDED_PHRASES = {
    "Команда не распознана": "voice/command_not_recognized.mp3",
    "Голос не соответствует эталону": "voice/voice_mismatch.mp3",
    "Не удалось выполнить команду": "voice/action_failed.mp3",
}


def beep() -> None:
    if shutil.which("paplay"):
        for path in _SOUND_CANDIDATES:
            try:
                subprocess.run(["paplay", path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
    # Терминальный звонок как последний резерв — работает почти везде
    sys.stdout.write("\a")
    sys.stdout.flush()


def speak(text: str) -> None:
    relative_path = _PRERECORDED_PHRASES.get(text)
    if relative_path and shutil.which("mpg123"):
        try:
            with resources.as_file(resources.files("audioreferent").joinpath(relative_path)) as audio_path:
                subprocess.run(
                    ["mpg123", "-q", str(audio_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
                )
            return
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            log.debug("Не удалось проиграть запись для %r, пробую espeak-ng", text)

    if shutil.which("espeak-ng"):
        subprocess.run(["espeak-ng", "-v", "ru", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif shutil.which("espeak"):
        subprocess.run(["espeak", "-v", "ru", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        log.debug("Голосовой движок не найден (espeak-ng/espeak), пропускаю: %s", text)
