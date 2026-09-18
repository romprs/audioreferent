import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audioreferent import phrase_cache


def _cache(tmp_path, monkeypatch, *, voice="0", rate=1.0):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return phrase_cache.PhraseCache("vosk", voice, rate, prebuilt_dir=tmp_path / "prebuilt")


def test_put_then_get_survives_a_new_cache_object(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    assert cache.get("Слушаю") is None
    cache.put("Слушаю", b"\x01\x02" * 10)
    assert _cache(tmp_path, monkeypatch).get("Слушаю") == b"\x01\x02" * 10  # пережил перезапуск


def test_voice_and_rate_are_part_of_the_key(tmp_path, monkeypatch):
    _cache(tmp_path, monkeypatch, voice="0", rate=1.0).put("Слушаю", b"aa")
    assert _cache(tmp_path, monkeypatch, voice="2", rate=1.0).get("Слушаю") is None  # другой голос
    assert _cache(tmp_path, monkeypatch, voice="0", rate=1.2).get("Слушаю") is None  # другая скорость
    assert _cache(tmp_path, monkeypatch, voice="0", rate=1.0).get("Слушаю") == b"aa"


def test_prebuilt_phrases_are_used_without_writing(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    prebuilt = tmp_path / "prebuilt" / "vosk" / "0"
    prebuilt.mkdir(parents=True)
    name = phrase_cache.key_for("Слушаю", engine="vosk", voice="0", rate=1.0) + ".pcm"
    (prebuilt / name).write_bytes(b"zz")
    assert cache.get("Слушаю") == b"zz"
    assert not (tmp_path / "cache").exists()  # ничего не писали


def test_broken_cache_does_not_raise(tmp_path, monkeypatch):
    cache = _cache(tmp_path, monkeypatch)
    # Путь занят файлом — создать каталог нельзя; кэш должен молча сдаться
    (tmp_path / "cache").write_text("не каталог", encoding="utf-8")
    cache.put("Слушаю", b"aa")
    assert cache.get("Слушаю") is None
    cache.put("Слушаю", b"aa")  # второй раз тоже без исключения
