"""Double-click entry point: starts the local Cadence server if it isn't already
running, then opens it in the default browser. No console window (run via
pythonw.exe) and no PHI involved -- this just manages the local process.

The server's output goes to `launcher.log` rather than to a console that does not exist.
CREATE_NO_WINDOW used to discard it, so ANY startup failure was invisible: the launcher polled a
dead port for 30 seconds and then opened the browser on nothing. That is not a hypothetical --
it happens whenever the database lock is held by another process (a seeding script, a second copy
of the app), which is a guard working exactly as designed and reporting itself to /dev/null. Now
a failure shows the reason in a dialog and points at the log.
"""

import socket
import subprocess
import time
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
PYTHON_EXE = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
LOG_PATH = PROJECT_ROOT / "launcher.log"
HOST, PORT = "127.0.0.1", 8420
URL = f"http://{HOST}:{PORT}/"

CREATE_NO_WINDOW = 0x08000000
STARTUP_TIMEOUT_S = 30


def is_server_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, PORT)) == 0


def start_server() -> subprocess.Popen:
    log = LOG_PATH.open("w", encoding="utf-8", errors="replace")
    return subprocess.Popen(
        [str(PYTHON_EXE), "-m", "uvicorn", "app.ui.server:app", "--host", HOST, "--port", str(PORT)],
        cwd=str(PROJECT_ROOT),
        stdout=log, stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW,
    )


def wait_for_server(proc: subprocess.Popen) -> bool:
    """Poll until the port answers. Returns early if the server process has already exited —
    waiting out the full timeout on a process that is gone helps nobody."""
    for _ in range(STARTUP_TIMEOUT_S * 2):
        if is_server_running():
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.5)
    return is_server_running()


def _tail(path: Path, lines: int = 12) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log was written)"


def report_failure() -> None:
    """Surface the reason. There is no console to print to, so use a dialog and fall back to the
    log file if even that is unavailable."""
    detail = _tail(LOG_PATH)
    message = (
        "Cadence could not start.\n\n"
        f"{detail}\n\n"
        f"Full log: {LOG_PATH}\n\n"
        "The most common cause is the database being open by something else — another copy of "
        "Cadence, or a script. Close it and try again."
    )
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, "Cadence", 0x10)  # MB_ICONERROR
    except Exception:  # noqa: BLE001 - a launcher must never die while reporting a death
        print(message)


def main() -> int:
    if is_server_running():
        webbrowser.open(URL)
        return 0
    proc = start_server()
    if not wait_for_server(proc):
        report_failure()
        return 1
    webbrowser.open(URL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
