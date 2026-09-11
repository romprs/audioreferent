import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audioreferent import actions


def test_background_launch_uses_systemd_run_when_available():
    with patch("audioreferent.actions.shutil.which", return_value="/usr/bin/systemd-run"), patch(
        "audioreferent.actions.subprocess.run"
    ) as mock_run, patch("audioreferent.actions.subprocess.Popen") as mock_popen:
        actions._run_background(["redmail"])
    argv = mock_run.call_args[0][0]
    assert argv[:5] == ["systemd-run", "--user", "--collect", "--quiet", "--"]
    assert argv[5:] == ["redmail"]
    mock_popen.assert_not_called()


def test_background_launch_falls_back_to_popen_without_systemd_run():
    with patch("audioreferent.actions.shutil.which", return_value=None), patch(
        "audioreferent.actions.subprocess.Popen"
    ) as mock_popen:
        actions._run_background(["redmail"])
    assert mock_popen.call_args[0][0] == ["redmail"]
    assert mock_popen.call_args[1]["start_new_session"] is True


def test_background_launch_falls_back_when_systemd_run_fails():
    import subprocess

    with patch("audioreferent.actions.shutil.which", return_value="/usr/bin/systemd-run"), patch(
        "audioreferent.actions.subprocess.run", side_effect=subprocess.CalledProcessError(1, "systemd-run")
    ), patch("audioreferent.actions.subprocess.Popen") as mock_popen:
        actions._run_background(["redmail"])
    mock_popen.assert_called_once()
