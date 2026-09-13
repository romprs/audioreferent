"""Оверлей модели Vosk с укороченными паузами конца фразы.

Детектор конца фразы Kaldi (endpoint.rule2/3/4.min-trailing-silence: тишина
после уверенного распознавания / после любого / вообще) у моделей Vosk
задан в самой модели, в conf/model.conf — 0.5 / 1.0 / 2.0 с. Установленный
vosk 0.3.45 не даёт менять это через API (методов SetEndpointerMode/
SetEndpointerDelays в нём нет, а готовых сборок новее нет ни на PyPI, ни в
релизах), но model.conf он читает при загрузке. Поэтому модель грузится
через «оверлей»: каталог в ~/.cache/audioreferent с символьными ссылками на
всё содержимое модели и копией conf/, где model.conf правлен. Модель из
RPM остаётся нетронутой; оверлей пересобирается, когда меняется пауза.

Отдельный модуль без импорта vosk — чтобы логику можно было проверить
тестами на машине без vosk."""

from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

_ENDPOINT_RULE_RE = re.compile(r"^--endpoint\.rule(\d)\.min-trailing-silence=.*$", re.MULTILINE)


def tuned_model_conf(text: str, end_silence_seconds: float) -> str:
    """model.conf с паузами: правило 2 = end_silence, 3 — вдвое, 4 — вчетверо
    больше. Отсутствующие правила добавляются."""
    values = {2: end_silence_seconds, 3: end_silence_seconds * 2, 4: end_silence_seconds * 4}

    def _replace(match: re.Match) -> str:
        rule = int(match.group(1))
        if rule not in values:
            return match.group(0)
        return f"--endpoint.rule{rule}.min-trailing-silence={values[rule]:.2f}"

    updated = _ENDPOINT_RULE_RE.sub(_replace, text)
    present = {int(m.group(1)) for m in _ENDPOINT_RULE_RE.finditer(updated)}
    missing = [
        f"--endpoint.rule{rule}.min-trailing-silence={value:.2f}" for rule, value in values.items() if rule not in present
    ]
    if missing:
        updated = updated.rstrip("\n") + "\n" + "\n".join(missing) + "\n"
    return updated


def overlay_dir_for(model_path: str, end_silence_seconds: float) -> Path:
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "audioreferent"
    return cache_root / f"vosk-overlay-{Path(model_path).name}-{end_silence_seconds:.2f}"


def prepare_model_with_endpointing(model_path: str, end_silence_seconds: float | None) -> str:
    """Каталог модели для загрузки: сама модель, либо оверлей (см. выше).
    Любая неудача — предупреждение в журнал и исходный каталог."""
    if not end_silence_seconds:
        return model_path
    source = Path(model_path)
    conf = source / "conf" / "model.conf"
    if not conf.is_file():
        return model_path
    try:
        overlay = overlay_dir_for(model_path, end_silence_seconds)
        expected = tuned_model_conf(conf.read_text(encoding="utf-8"), end_silence_seconds)
        overlay_conf = overlay / "conf" / "model.conf"
        if (
            overlay.is_dir()
            and overlay_conf.is_file()
            and overlay_conf.read_text(encoding="utf-8") == expected
            and all((overlay / entry.name).exists() for entry in source.iterdir())
        ):
            return str(overlay)
        shutil.rmtree(overlay, ignore_errors=True)
        overlay.mkdir(parents=True)
        for entry in source.iterdir():
            if entry.name == "conf":
                shutil.copytree(entry, overlay / "conf")
            else:
                os.symlink(entry, overlay / entry.name, target_is_directory=entry.is_dir())
        overlay_conf.write_text(expected, encoding="utf-8")
        log.info("Модель с паузой конца фразы %.2f с: %s", end_silence_seconds, overlay)
        return str(overlay)
    except OSError as exc:
        log.warning("Не удалось подготовить оверлей модели (%s) — пауза конца фразы по умолчанию", exc)
        return model_path
