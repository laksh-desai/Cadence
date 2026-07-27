"""Double-click entry point: starts the local Cadence server if it isn't already
running, then opens it in the default browser. No console window (run via
pythonw.exe) and no PHI involved -- this just manages the local process."""

import socket
import subprocess
import time
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
PYTHON_EXE = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
HOST, PORT = "127.0.0.1", 8420
URL = f"http://{HOST}:{PORT}/"

CREATE_NO_WINDOW = 0x08000000


def is_server_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, PORT)) == 0


def start_server() -> None:
    subprocess.Popen(
        [str(PYTHON_EXE), "-m", "uvicorn", "app.ui.server:app", "--host", HOST, "--port", str(PORT)],
        cwd=str(PROJECT_ROOT),
        creationflags=CREATE_NO_WINDOW,
    )
    for _ in range(60):
        if is_server_running():
            return
        time.sleep(0.5)


def main() -> None:
    if not is_server_running():
        start_server()
    webbrowser.open(URL)


if __name__ == "__main__":
    main()
