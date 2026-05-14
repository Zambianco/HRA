import os
import socket
import threading
import time
import json
import sqlite3
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from urllib.error import URLError
from urllib.request import urlopen

import webview
from django.core.management import execute_from_command_line


def _wait_for_server(url: str, timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=1.5) as response:
                if response.status < 500:
                    return
        except (URLError, OSError):
            time.sleep(0.2)

    raise RuntimeError(f"Servidor Django nao respondeu em {url} dentro do tempo limite.")


def _run_django(host: str, port: int) -> None:
    execute_from_command_line(
        [
            "manage.py",
            "runserver",
            f"{host}:{port}",
            "--noreload",
            "--nothreading",
            "--insecure",
        ]
    )


def _pick_port(default_port: int = 8000) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("127.0.0.1", default_port)) != 0:
            return default_port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _normalize_db_path(path_value: str, base_dir: Path, data_dir: Path) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return str(data_dir / "rh.db")

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate

    try:
        resolved = candidate.resolve(strict=False)
        _ = resolved.parent.exists()
    except OSError:
        return str(data_dir / "rh.db")

    return str(resolved)


def _apply_database_mode_from_saved_config() -> None:
    base_dir = Path(__file__).resolve().parent
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    config_path = data_dir / "db_config.json"

    mode = "arquivo"
    db_file_path = str(data_dir / "rh.db")

    if config_path.exists():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            loaded = {}

        if isinstance(loaded, dict):
            loaded_mode = str(loaded.get("mode", "")).strip().lower()
            loaded_path = str(loaded.get("db_file_path", "")).strip()
            if loaded_mode in {"online", "arquivo"}:
                mode = loaded_mode
            db_file_path = _normalize_db_path(loaded_path, base_dir, data_dir)

    if mode == "arquivo":
        while True:
            db_path = Path(db_file_path).expanduser()
            if db_path.exists() and _sqlite_has_required_schema(str(db_path)):
                break

            selected_db = _prompt_for_database_file(initial_dir=data_dir)
            if not selected_db:
                raise RuntimeError(
                    "Banco de dados invalido/nao encontrado e nenhum arquivo foi selecionado."
                )
            db_file_path = selected_db

        config_path.write_text(
            json.dumps(
                {
                    "mode": mode,
                    "db_file_path": db_file_path,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    os.environ["DATABASE_MODE"] = mode
    if mode == "arquivo":
        os.environ["DB_FILE_PATH"] = db_file_path
    else:
        os.environ.pop("DB_FILE_PATH", None)


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    _apply_database_mode_from_saved_config()
    host = "127.0.0.1"
    port = _pick_port()
    base_url = f"http://{host}:{port}/"

    server_thread = threading.Thread(target=_run_django, args=(host, port), daemon=True)
    server_thread.start()

    _wait_for_server(base_url)
    webview.create_window("RH Local", base_url, width=1280, height=820, min_size=(960, 640))
    webview.start(debug=False)


if __name__ == "__main__":
    main()
