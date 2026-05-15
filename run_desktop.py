import os
import socket
import threading
import time
import json
import sqlite3
import subprocess
import sys
import re
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from urllib.error import URLError
from urllib.request import Request, urlopen

import webview
from django.core.management import execute_from_command_line


REQUIRED_SQLITE_TABLES = {
    "django_migrations",
    "employees_employee",
}
APP_VERSION = "1.0.0"
GITHUB_REPO = os.environ.get("HRA_GITHUB_REPO", "Zambianco/HRA").strip()


class DesktopApi:
    def save_text_file(self, default_name: str, content: str) -> dict:
        root = tk.Tk()
        root.withdraw()
        try:
            selected = filedialog.asksaveasfilename(
                title="Salvar arquivo",
                defaultextension=".csv",
                initialfile=default_name or "arquivo.csv",
                filetypes=[("CSV", "*.csv"), ("Todos os arquivos", "*.*")],
            )
        finally:
            root.destroy()

        if not selected:
            return {"ok": False, "cancelled": True}

        target = Path(selected)
        target.write_text(content or "", encoding="utf-8")
        return {"ok": True, "path": str(target)}


def _parse_semver(version_value: str) -> tuple[int, int, int] | None:
    raw = str(version_value or "").strip()
    if raw.lower().startswith("v"):
        raw = raw[1:]
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", raw)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _fetch_latest_release(repo: str, timeout_seconds: float = 3.0) -> dict | None:
    if not repo or "/" not in repo:
        return None
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "hra-desktop-updater",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except (URLError, OSError, TimeoutError):
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None
    return data


def _check_for_updates(current_version: str, repo: str) -> None:
    release_data = _fetch_latest_release(repo=repo)
    if not release_data:
        return

    latest_tag = str(release_data.get("tag_name", "")).strip()
    latest_tuple = _parse_semver(latest_tag)
    current_tuple = _parse_semver(current_version)
    if not latest_tuple or not current_tuple:
        return
    if latest_tuple <= current_tuple:
        return

    html_url = str(release_data.get("html_url", "")).strip()
    published_at = str(release_data.get("published_at", "")).strip()

    messagebox.showinfo(
        "Atualizacao disponivel",
        (
            f"Versao atual: v{current_version}\n"
            f"Nova versao disponivel: {latest_tag}\n\n"
            f"Publicada em: {published_at or 'data indisponivel'}\n"
            f"Baixe em: {html_url or 'link indisponivel'}"
        ),
    )


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


def _sqlite_has_required_schema(db_file_path: str) -> bool:
    target = Path(db_file_path).expanduser()
    if not target.exists() or not target.is_file():
        return False

    try:
        with sqlite3.connect(str(target)) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
    except sqlite3.Error:
        return False

    table_names = {str(row[0]) for row in rows if row and row[0]}
    return REQUIRED_SQLITE_TABLES.issubset(table_names)


def _run_migrate_for_sqlite(db_file_path: str, base_dir: Path) -> tuple[bool, str]:
    db_target = Path(db_file_path).expanduser()
    db_target.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["DATABASE_MODE"] = "arquivo"
    env["DB_FILE_PATH"] = str(db_target)
    env.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    completed = subprocess.run(
        [sys.executable, "manage.py", "migrate", "--noinput"],
        cwd=str(base_dir),
        env=env,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip() or (completed.stdout or "").strip()
        return False, detail[:800]
    return True, ""


def _prompt_for_database_file(initial_dir: Path) -> str:
    root = tk.Tk()
    root.withdraw()
    try:
        selected = filedialog.askopenfilename(
            title="Selecione um arquivo de banco SQLite (.db)",
            initialdir=str(initial_dir),
            filetypes=[("SQLite DB", "*.db"), ("Todos os arquivos", "*.*")],
        )
    finally:
        root.destroy()
    return str(selected or "").strip()


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

            should_create = messagebox.askyesno(
                "Banco de dados nao encontrado",
                (
                    "O arquivo de banco nao existe ou esta sem estrutura.\n\n"
                    "Deseja criar um novo banco neste caminho e aplicar migrate agora?"
                ),
            )
            if should_create:
                created, error_detail = _run_migrate_for_sqlite(str(db_path), base_dir)
                if created and _sqlite_has_required_schema(str(db_path)):
                    break
                messagebox.showerror(
                    "Falha ao criar banco",
                    "Nao foi possivel criar o banco com migrate.\n\n"
                    f"Detalhe: {error_detail or 'erro desconhecido.'}",
                )

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
    _check_for_updates(current_version=APP_VERSION, repo=GITHUB_REPO)
    host = "127.0.0.1"
    port = _pick_port()
    base_url = f"http://{host}:{port}/"

    server_thread = threading.Thread(target=_run_django, args=(host, port), daemon=True)
    server_thread.start()

    _wait_for_server(base_url)
    webview.create_window(
        "RH Local",
        base_url,
        width=1280,
        height=820,
        min_size=(960, 640),
        js_api=DesktopApi(),
    )
    webview.start(debug=False)


if __name__ == "__main__":
    main()
