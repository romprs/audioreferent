import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audioreferent import config as config_mod
from audioreferent.config import CommandSpec, load_config, save_config


def _redirect_user_config(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "USER_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "USER_CONFIG_PATH", tmp_path / "config.yaml")
    return tmp_path / "config.yaml"


def test_save_omits_commands_when_equal_to_package_defaults(monkeypatch, tmp_path):
    path = _redirect_user_config(monkeypatch, tmp_path)
    cfg = load_config()  # ровно умолчания пакета, пользовательского файла нет
    cfg.feedback.speech = True
    save_config(cfg)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "commands" not in data
    assert data["feedback"] == {"sound": True, "speech": True}


def test_save_writes_commands_when_user_changed_them(monkeypatch, tmp_path):
    path = _redirect_user_config(monkeypatch, tmp_path)
    cfg = load_config()
    cfg.commands.append(CommandSpec(phrases=["скажи привет"], action="search_web", args={}))
    save_config(cfg)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["commands"][-1]["phrases"] == ["скажи привет"]
    # и после перезагрузки пользовательский список действительно применяется
    assert load_config().commands[-1].phrases == ["скажи привет"]


def test_new_default_phrases_reach_user_who_never_edited_commands(monkeypatch, tmp_path):
    _redirect_user_config(monkeypatch, tmp_path)
    save_config(load_config())
    phrases = [p for spec in load_config().commands for p in spec.phrases]
    assert "запусти почту" in phrases
