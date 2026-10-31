"""launcher.py testleri (exe/frozen yolları ve port seçimi)."""

from __future__ import annotations

import importlib
import os
import socket
import sys
from pathlib import Path

import launcher


def test_app_dir_uses_meipass_when_frozen(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    importlib.reload(launcher)
    assert launcher.app_dir() == tmp_path


def test_app_dir_falls_back_to_source_dir(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    importlib.reload(launcher)
    assert launcher.app_dir() == Path(launcher.__file__).resolve().parent


def test_prepare_sets_env_for_frozen_app(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.delenv("NOVA_STATIC_DIR", raising=False)
    monkeypatch.delenv("NOVA_MEMORY_DB", raising=False)
    monkeypatch.delenv("NOVA_PORT", raising=False)
    importlib.reload(launcher)

    base, port, url = launcher.prepare()
    assert base == tmp_path
    assert os.environ["NOVA_STATIC_DIR"] == str(tmp_path)
    assert os.environ["NOVA_MEMORY_DB"].endswith(os.path.join("Nova", "nova.db"))
    assert (tmp_path / "appdata" / "Nova").is_dir()
    assert port >= 5000
    assert url.endswith(str(port))


def test_first_free_port_skips_busy_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        taken = busy.getsockname()[1]
        busy.listen(1)
        free = launcher.first_free_port(taken, tries=25)
        assert free != taken
