"""Nova v2 - tek dosya (.exe) baslatici.

PyInstaller ile paketlendiginde:
  - index.html / app.js / styles.css dosyalari _MEIPASS icinden servis edilir
  - kalici hafiza %APPDATA%\\Nova\\nova.db altinda tutulur
  - bos port bulunur, tarayici kendiliginden acilir

Gelistirme modunda (python launcher.py) normal klasorden calisir.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path


def app_dir() -> Path:
    """Statik dosyalarin bulundugu klasor (frozen ise gecici cikarma dizini)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def first_free_port(start: int = 5000, tries: int = 25) -> int:
    """5000'den baslayarak bos bir port dondurur."""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    return start


def prepare() -> tuple[Path, int, str]:
    """Ortam degiskenlerini ayarlar; (statik dizin, port, adres) dondurur."""
    base = app_dir()
    os.environ.setdefault("NOVA_STATIC_DIR", str(base))

    if getattr(sys, "frozen", False):
        data_dir = Path(os.environ.get("APPDATA") or Path.home()) / "Nova"
        data_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("NOVA_MEMORY_DB", str(data_dir / "nova.db"))

    requested = int(os.environ.get("NOVA_PORT") or 0)
    port = requested or first_free_port(5000)
    return base, port, f"http://127.0.0.1:{port}"


def main() -> None:
    _, port, url = prepare()

    print("=" * 64)
    print("  Nova v2 - Turkce yapay zeka asistani")
    print(f"  Adres  : {url}")
    print("  Kapat  : Ctrl + C  (veya pencereyi kapat)")
    print("=" * 64, flush=True)

    threading.Timer(2.0, lambda: webbrowser.open(url)).start()

    import uvicorn

    from server import app

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
