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


def test_user_commands_are_merged_over_defaults_not_replacing_them(monkeypatch, tmp_path):
    """Снимок команд, сохранённый из GUI (даже с правками), не должен
    замораживать старые действия и прятать новые фразы пакета."""
    path = _redirect_user_config(monkeypatch, tmp_path)
    path.write_text(
        yaml.safe_dump(
            {
                "commands": [
                    # старое действие + своя фраза: как в реальном конфиге на .80
                    {"phrases": ["создай встречу", "создай совещание"], "action": "redmail_create_event", "args": {}},
                    # своя правка умолчания: те же action/args -> фразы объединяются
                    {"phrases": ["браузер"], "action": "launch_app", "args": {"default_browser": True, "candidates": ["firefox", "chromium", "chromium-browser", "google-chrome-stable", "google-chrome"]}},
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    cfg = load_config()
    by_action = {}
    for spec in cfg.commands:
        by_action.setdefault(spec.action, []).append(spec)

    # умолчания пакета на месте, в т.ч. новая форма встречи и её инфинитивные фразы
    form_phrases = [p for spec in by_action["redmail_event_form"] for p in spec.phrases]
    assert "создай встречу" in form_phrases and "создать встречу" in form_phrases
    # своя фраза пользователя сохранилась (команда без пары добавлена в конец)
    assert by_action["redmail_create_event"][0].phrases == ["создай встречу", "создай совещание"]
    # правка умолчания: свои фразы + новые из пакета
    browser = next(s for s in by_action["launch_app"] if s.args.get("default_browser"))
    assert browser.phrases[0] == "браузер" and "открой браузер" in browser.phrases
    # умолчания, которых пользователь не трогал, остались
    assert any(s.action == "lock_screen" for s in cfg.commands)


def test_event_form_words_loaded_from_defaults_and_saved_only_when_changed(monkeypatch, tmp_path):
    path = _redirect_user_config(monkeypatch, tmp_path)
    cfg = load_config()
    assert "тема" in cfg.event_form.fields["subject"]
    assert cfg.event_form.save == ["сохранить", "сохрани"]
    save_config(cfg)
    assert "event_form" not in yaml.safe_load(path.read_text(encoding="utf-8"))

    cfg.event_form.fields["subject"] = ["тема", "заголовок"]
    save_config(cfg)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["event_form"]["fields"]["subject"] == ["тема", "заголовок"]
    assert load_config().event_form.fields["subject"] == ["тема", "заголовок"]


def test_new_default_phrases_reach_user_who_never_edited_commands(monkeypatch, tmp_path):
    _redirect_user_config(monkeypatch, tmp_path)
    save_config(load_config())
    phrases = [p for spec in load_config().commands for p in spec.phrases]
    assert "запусти почту" in phrases
