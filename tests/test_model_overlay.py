import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audioreferent import model_overlay

MODEL_CONF = """--min-active=200
--beam=13.0
--endpoint.silence-phones=1:2:3:4:5:6:7:8:9:10
--endpoint.rule2.min-trailing-silence=0.5
--endpoint.rule3.min-trailing-silence=1.0
--endpoint.rule4.min-trailing-silence=2.0
"""


def test_tuned_conf_scales_rules_2_3_4_and_keeps_the_rest():
    tuned = model_overlay.tuned_model_conf(MODEL_CONF, 0.4)
    assert "--endpoint.rule2.min-trailing-silence=0.40" in tuned
    assert "--endpoint.rule3.min-trailing-silence=0.80" in tuned
    assert "--endpoint.rule4.min-trailing-silence=1.60" in tuned
    assert "--min-active=200" in tuned and "--endpoint.silence-phones=1:2:3:4:5:6:7:8:9:10" in tuned
    assert tuned.count("min-trailing-silence") == 3


def test_tuned_conf_adds_missing_rules():
    tuned = model_overlay.tuned_model_conf("--beam=13.0\n", 0.3)
    assert tuned.endswith(
        "--endpoint.rule2.min-trailing-silence=0.30\n--endpoint.rule3.min-trailing-silence=0.60\n--endpoint.rule4.min-trailing-silence=1.20\n"
    )


def _fake_model(tmp_path: Path) -> Path:
    model = tmp_path / "vosk-model"
    (model / "conf").mkdir(parents=True)
    (model / "conf" / "model.conf").write_text(MODEL_CONF, encoding="utf-8")
    (model / "conf" / "mfcc.conf").write_text("--sample-frequency=16000\n", encoding="utf-8")
    (model / "am").mkdir()
    (model / "am" / "final.mdl").write_bytes(b"model")
    (model / "graph").mkdir()
    (model / "graph" / "HCLG.fst").write_bytes(b"graph")
    return model


def test_overlay_links_model_and_rewrites_conf(monkeypatch, tmp_path):
    model = _fake_model(tmp_path)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    links: list[tuple[Path, Path]] = []

    def fake_symlink(src, dst, target_is_directory=False):  # символьные ссылки на Windows требуют прав
        links.append((Path(src), Path(dst)))
        (Path(dst)).mkdir() if target_is_directory else Path(dst).write_bytes(b"link")

    monkeypatch.setattr(model_overlay.os, "symlink", fake_symlink)
    overlay = Path(model_overlay.prepare_model_with_endpointing(str(model), 0.4))
    assert overlay != model and overlay.parent == tmp_path / "cache" / "audioreferent"
    assert {dst.name for _src, dst in links} == {"am", "graph"}  # всё, кроме conf — ссылками
    assert (overlay / "conf" / "mfcc.conf").read_text(encoding="utf-8") == "--sample-frequency=16000\n"  # conf скопирован
    assert "--endpoint.rule2.min-trailing-silence=0.40" in (overlay / "conf" / "model.conf").read_text(encoding="utf-8")
    # повторный вызов с той же паузой переиспользует готовый оверлей, не пересобирая его
    links.clear()
    assert Path(model_overlay.prepare_model_with_endpointing(str(model), 0.4)) == overlay
    assert links == []
    # другая пауза — другой оверлей
    assert Path(model_overlay.prepare_model_with_endpointing(str(model), 0.6)) != overlay


def test_overlay_falls_back_to_model_on_failure(monkeypatch, tmp_path):
    model = _fake_model(tmp_path)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    def failing_symlink(*_args, **_kwargs):
        raise OSError("symlink not permitted")

    monkeypatch.setattr(model_overlay.os, "symlink", failing_symlink)
    assert model_overlay.prepare_model_with_endpointing(str(model), 0.4) == str(model)
    assert model_overlay.prepare_model_with_endpointing(str(model), None) == str(model)
    assert model_overlay.prepare_model_with_endpointing(str(tmp_path / "no-conf"), 0.4) == str(tmp_path / "no-conf")
