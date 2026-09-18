"""Отдать память модели распознавания в своп, пока помощник простаивает.

Зачем: модель Vosk (`vosk-model-ru-0.42`) держит ~1,1 ГБ, и держит их
круглосуточно — ради одного активационного слова. Выгружать модель целиком
дорого: обратная загрузка занимает ~6 с, это заметная пауза на первой
команде. Вместо этого просим ядро вытеснить страницы процесса в своп
(`madvise(MADV_PAGEOUT)`): в простое RSS падает с ~1150 до ~40 МБ, а при
следующей команде страницы возвращаются лениво — замер на рабочей станции
дал ~1 с и RSS ~260 МБ (возвращается только то, что реально нужно для
декодирования). Модель при этом остаётся загруженной, качество не меняется.

Куда уходят страницы, решает ядро по приоритетам свопа: zram (сжатие в той
же ОЗУ, ~2,4x) или раздел на диске (освобождает память полностью, возврат
с NVMe быстрый).

Только Linux; на других системах и при любой ошибке — тихо ничего не
делаем, помощник продолжает работать как раньше.
"""

from __future__ import annotations

import ctypes
import logging
import re
import sys
from pathlib import Path

log = logging.getLogger(__name__)

#: madvise(2), Linux 5.4+: «эти страницы скоро не понадобятся — вытесни их».
MADV_PAGEOUT = 21

#: Меньшие области трогать незачем: там код, стеки и мелочь, выигрыша нет,
#: а возвращать их придётся сразу же.
DEFAULT_MIN_BYTES = 8 * 1024 * 1024

_MAPS_LINE = re.compile(r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S{4})\s+\S+\s+\S+\s+\S+\s*(.*)$")


def large_anonymous_ranges(maps_text: str, min_bytes: int = DEFAULT_MIN_BYTES) -> list[tuple[int, int]]:
    """(адрес, размер) крупных анонимных областей чтения-записи из
    /proc/self/maps — в них лежит модель. Файловые отображения пропускаем:
    их страницы и так сбрасываются без свопа, а вытеснять исполняемый код
    значит замедлить сам процесс."""
    ranges: list[tuple[int, int]] = []
    for line in maps_text.splitlines():
        match = _MAPS_LINE.match(line)
        if not match:
            continue
        start, end, perms, path = int(match.group(1), 16), int(match.group(2), 16), match.group(3), match.group(4).strip()
        if path and not path.startswith("[heap]"):
            continue  # файл или особая область (стек, vdso) — не трогаем
        if not perms.startswith("rw"):
            continue
        size = end - start
        if size >= min_bytes:
            ranges.append((start, size))
    return ranges


def rss_mb() -> float:
    """Текущий RSS процесса в мегабайтах (0.0, если не Linux)."""
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def page_out(min_bytes: int = DEFAULT_MIN_BYTES) -> float:
    """Вытеснить свои крупные анонимные области. Возвращает, сколько
    мегабайт было предложено ядру (0 — ничего не сделали)."""
    if not sys.platform.startswith("linux"):
        return 0.0
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        maps = Path("/proc/self/maps").read_text(encoding="utf-8")
    except (OSError, AttributeError) as exc:
        log.debug("Вытеснение в своп недоступно: %s", exc)
        return 0.0
    before = rss_mb()
    advised = 0
    for start, size in large_anonymous_ranges(maps, min_bytes):
        if libc.madvise(ctypes.c_void_p(start), ctypes.c_size_t(size), MADV_PAGEOUT) == 0:
            advised += size
    if advised:
        log.info(
            "Простой: память отдана в своп (%.0f МБ предложено, RSS %.0f -> %.0f МБ)",
            advised / 1024 / 1024,
            before,
            rss_mb(),
        )
    return advised / 1024 / 1024
