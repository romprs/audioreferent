import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audioreferent.commands import CommandRegistry
from audioreferent.config import CommandSpec

REGISTRY = CommandRegistry(
    [
        CommandSpec(phrases=["открой браузер", "запусти браузер"], action="launch_app", args={"a": 1}),
        CommandSpec(phrases=["сделай тише"], action="volume_change", args={"delta": -10}),
    ]
)


def test_matches_known_phrase():
    match = REGISTRY.match("вика открой браузер пожалуйста")
    assert match is not None
    assert match.spec.action == "launch_app"


def test_no_match_for_unknown_text():
    assert REGISTRY.match("расскажи анекдот") is None


def test_empty_text_no_match():
    assert REGISTRY.match("") is None
