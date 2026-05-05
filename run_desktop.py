import os
import socket
import threading
import time
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
        ["manage.py", "runserver", f"{host}:{port}", "--noreload", "--nothreading"]
    )


def _pick_port(default_port: int = 8000) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("127.0.0.1", default_port)) != 0:
            return default_port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
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
