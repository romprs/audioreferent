import json
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audioreferent import redmail_client
from audioreferent.redmail_client import RedmailNotRunning


def _endpoint(monkeypatch, tmp_path, full_server_name):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    d = tmp_path / "redmail"
    d.mkdir()
    (d / "ipc-endpoint.json").write_text(
        json.dumps({"protocol": "jsonl-v1", "name": "redmail-ipc", "full_server_name": full_server_name, "pid": 1}),
        encoding="utf-8",
    )


def test_missing_endpoint_file_means_not_running(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    with pytest.raises(RedmailNotRunning):
        redmail_client.focus()


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="unix-сокеты — только на POSIX")
def test_stale_endpoint_means_not_running(monkeypatch, tmp_path):
    # Файл адреса есть, но сокета по нему никто не слушает (redmail умер
    # без очистки) — это тоже «почта не запущена», а не ошибка связи.
    _endpoint(monkeypatch, tmp_path, str(tmp_path / "no-such-socket"))
    with pytest.raises(RedmailNotRunning):
        redmail_client.focus()
