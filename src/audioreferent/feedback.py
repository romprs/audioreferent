"""Звуковая/голосовая обратная связь пользователю."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys

log = logging.getLogger(__name__)

_SOUND_CANDIDATES = [
    "/usr/share/sounds/freedesktop/stereo/message.oga",
    "/usr/share/sounds/freedesktop/stereo/complete.oga",
]


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
    if shutil.which("espeak-ng"):
        subprocess.run(["espeak-ng", "-v", "ru", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif shutil.which("espeak"):
        subprocess.run(["espeak", "-v", "ru", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        log.debug("Голосовой движок не найден (espeak-ng/espeak), пропускаю: %s", text)
