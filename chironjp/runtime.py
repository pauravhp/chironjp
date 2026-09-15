"""Isolated Chromium startup from Chiron's proven worker runtime."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from .paths import private_dir, private_file
from .registry import Registry, Worker
from .takeover import port_open, start_surface


def hermes_cli() -> str:
    command = shutil.which("hermes")
    if not command:
        raise RuntimeError("Hermes CLI is not available on PATH")
    return command


def _owned_chromium_pid(worker: Worker) -> int | None:
    try:
        pid = int((worker.workspace / "chromium.pid").read_text(encoding="ascii").strip())
        command = (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except (OSError, ValueError):
        return None
    required = (
        f"--user-data-dir={worker.chromium_profile}",
        f"--remote-debugging-port={worker.cdp_port}",
    )
    return pid if all(marker in command for marker in required) else None


def start_chromium(
    registry: Registry,
    worker: Worker,
    *,
    initial_url: str = "about:blank",
    novnc_web: str | Path = "/usr/share/novnc",
) -> dict[str, str | int | bool]:
    if port_open(worker.cdp_port):
        pid = _owned_chromium_pid(worker)
        if pid is None:
            raise RuntimeError(f"CDP port {worker.cdp_port} is occupied without ownership proof")
        return {"started": False, "port": worker.cdp_port, "pid": pid,
                "reason": "owned_browser_already_listening"}
    private_dir(worker.chromium_profile)
    private_dir(worker.workspace)
    start_surface(worker, novnc_web=novnc_web)
    chromium = shutil.which("chromium") or shutil.which("chromium-browser")
    if not chromium:
        raise RuntimeError("Chromium executable is unavailable")
    command = [
        chromium,
        f"--user-data-dir={worker.chromium_profile}",
        f"--remote-debugging-port={worker.cdp_port}",
        "--remote-debugging-address=127.0.0.1",
        "--no-first-run", "--window-size=1440,1000", "--window-position=0,0",
        "--no-default-browser-check", "--disable-sync", "--disable-background-networking",
        "--disable-dev-shm-usage", "--no-sandbox", initial_url,
    ]
    log_path = worker.workspace / "chromium.log"
    pid_path = worker.workspace / "chromium.pid"
    with log_path.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=log, start_new_session=True,
            env={**os.environ, "DISPLAY": worker.x_display},
        )
    pid_path.write_text(str(process.pid), encoding="ascii")
    private_file(log_path)
    private_file(pid_path)
    for _ in range(50):
        if port_open(worker.cdp_port):
            return {"started": True, "port": worker.cdp_port, "pid": process.pid}
        if process.poll() is not None:
            raise RuntimeError(f"Chromium exited with code {process.returncode}; inspect its private log")
        time.sleep(0.1)
    raise RuntimeError(f"Chromium did not expose configured CDP port {worker.cdp_port}")


def stop_chromium(worker: Worker) -> dict[str, str | int | bool]:
    pid = _owned_chromium_pid(worker)
    if pid is None:
        if port_open(worker.cdp_port):
            raise RuntimeError(f"CDP port {worker.cdp_port} is occupied without ownership proof")
        return {"stopped": False, "reason": "owned_browser_not_running"}
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if not (Path("/proc") / str(pid)).exists() and not port_open(worker.cdp_port):
            return {"stopped": True, "pid": pid}
        time.sleep(0.1)
    raise RuntimeError(f"owned Chromium {pid} did not stop")
