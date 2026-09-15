"""Localhost-only, view-only noVNC surface from Chiron's proven takeover path."""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from .paths import private_dir, private_file
from .registry import Worker


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.2)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def _required_command(name: str) -> str:
    command = shutil.which(name)
    if not command:
        raise RuntimeError(f"required command is unavailable: {name}")
    return command


def surface_commands(worker: Worker, *, novnc_web: str | Path = "/usr/share/novnc") -> dict[str, list[str]]:
    web_root = Path(novnc_web).resolve()
    if not web_root.is_dir():
        raise RuntimeError(f"noVNC web root is unavailable: {web_root}")
    return {
        "xvfb": [
            _required_command("Xvfb"), worker.x_display,
            "-screen", "0", "1440x1000x24", "-ac", "-noreset", "-nolisten", "tcp",
        ],
        "x11vnc": [
            _required_command("x11vnc"), "-display", worker.x_display,
            "-rfbport", str(worker.vnc_port), "-localhost", "-forever", "-shared",
            "-nopw", "-noxdamage", "-viewonly",
        ],
        "websockify": [
            _required_command("websockify"), f"--web={web_root}", "--file-only",
            f"127.0.0.1:{worker.novnc_port}", f"127.0.0.1:{worker.vnc_port}",
        ],
    }


def _markers(worker: Worker) -> dict[str, tuple[str, ...]]:
    return {
        "xvfb": ("Xvfb", worker.x_display),
        "x11vnc": ("x11vnc", "-display", worker.x_display, "-rfbport", str(worker.vnc_port)),
        "websockify": ("websockify", f"127.0.0.1:{worker.novnc_port}", f"127.0.0.1:{worker.vnc_port}"),
    }


def _cmdline(pid: int) -> str | None:
    try:
        return (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return None


def _owned_pid(pid_path: Path, markers: tuple[str, ...]) -> int | None:
    try:
        pid = int(pid_path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    command = _cmdline(pid)
    if command is None:
        pid_path.unlink(missing_ok=True)
        return None
    if not all(marker in command for marker in markers):
        raise RuntimeError(f"PID {pid} is live but does not match this ChironJP surface")
    return pid


def _spawn(base: Path, name: str, command: list[str], markers: tuple[str, ...]) -> tuple[int, bool]:
    pid_path = base / f"{name}.pid"
    existing = _owned_pid(pid_path, markers)
    if existing is not None:
        return existing, False
    log_path = base / f"{name}.log"
    with log_path.open("ab", buffering=0) as log:
        process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
    pid_path.write_text(str(process.pid), encoding="ascii")
    private_file(pid_path)
    private_file(log_path)
    return process.pid, True


def _wait(pid: int, ready: Any, label: str) -> None:
    for _ in range(80):
        if _cmdline(pid) is None:
            raise RuntimeError(f"{label} exited before becoming ready")
        if ready():
            return
        time.sleep(0.1)
    raise RuntimeError(f"{label} did not become ready")


def start_surface(worker: Worker, *, novnc_web: str | Path = "/usr/share/novnc") -> dict[str, Any]:
    """Start only the worker-owned local surface; input remains disabled."""
    base = worker.workspace / "takeover"
    private_dir(base)
    commands = surface_commands(worker, novnc_web=novnc_web)
    markers = _markers(worker)
    socket_path = Path(f"/tmp/.X11-unix/X{worker.display}")
    if socket_path.exists() and _owned_pid(base / "xvfb.pid", markers["xvfb"]) is None:
        raise RuntimeError(f"X display {worker.x_display} is occupied without ownership proof")
    xvfb_pid, xvfb_started = _spawn(base, "xvfb", commands["xvfb"], markers["xvfb"])
    _wait(xvfb_pid, socket_path.exists, "Xvfb")
    if port_open(worker.vnc_port) and _owned_pid(base / "x11vnc.pid", markers["x11vnc"]) is None:
        raise RuntimeError(f"VNC port {worker.vnc_port} is occupied without ownership proof")
    vnc_pid, vnc_started = _spawn(base, "x11vnc", commands["x11vnc"], markers["x11vnc"])
    _wait(vnc_pid, lambda: port_open(worker.vnc_port), "x11vnc")
    if port_open(worker.novnc_port) and _owned_pid(base / "websockify.pid", markers["websockify"]) is None:
        raise RuntimeError(f"noVNC port {worker.novnc_port} is occupied without ownership proof")
    web_pid, web_started = _spawn(base, "websockify", commands["websockify"], markers["websockify"])
    _wait(web_pid, lambda: port_open(worker.novnc_port), "websockify")
    return {
        "worker": worker.id, "display": worker.x_display,
        "vnc_port": worker.vnc_port, "novnc_port": worker.novnc_port,
        "localhost_only": True, "view_only": True,
        "url": f"http://127.0.0.1:{worker.novnc_port}/vnc.html?autoconnect=1&resize=scale",
        "started": {"xvfb": xvfb_started, "x11vnc": vnc_started, "websockify": web_started},
    }


def _stop(base: Path, name: str, markers: tuple[str, ...]) -> bool:
    pid_path = base / f"{name}.pid"
    pid = _owned_pid(pid_path, markers)
    if pid is None:
        return False
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if _cmdline(pid) is None:
            pid_path.unlink(missing_ok=True)
            return True
        time.sleep(0.1)
    raise RuntimeError(f"owned surface process {name} ({pid}) did not stop")


def stop_surface(worker: Worker) -> dict[str, Any]:
    base = worker.workspace / "takeover"
    markers = _markers(worker)
    return {
        "worker": worker.id,
        "stopped": {name: _stop(base, name, markers[name]) for name in ("websockify", "x11vnc", "xvfb")},
    }
