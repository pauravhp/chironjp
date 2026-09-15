"""Generic-path adaptation of Chiron's data-driven worker registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .paths import real, require_within


@dataclass(frozen=True)
class Worker:
    id: str
    enabled: bool
    hermes_profile: str
    hermes_profile_root: Path
    chromium_profile: Path
    workspace: Path
    cdp_port: int
    display: int
    vnc_port: int
    novnc_port: int

    @property
    def cdp_url(self) -> str:
        return f"http://127.0.0.1:{self.cdp_port}"

    @property
    def x_display(self) -> str:
        return f":{self.display}"

    @property
    def hermes_home(self) -> Path:
        return self.hermes_profile_root / self.hermes_profile


@dataclass(frozen=True)
class Tailor:
    id: str
    hermes_profile: str
    hermes_profile_root: Path
    workspace: Path
    provider: str
    model: str
    reasoning: str

    @property
    def hermes_home(self) -> Path:
        return self.hermes_profile_root / self.hermes_profile


@dataclass(frozen=True)
class Registry:
    path: Path
    runtime_root: Path
    state_root: Path
    database: Path
    workers: tuple[Worker, ...]
    tailor: Tailor

    def worker(self, worker_id: str, *, allow_disabled: bool = False) -> Worker:
        for worker in self.workers:
            if worker.id == worker_id:
                if not worker.enabled and not allow_disabled:
                    raise ValueError(f"worker {worker_id!r} is disabled")
                return worker
        raise ValueError(f"unknown worker {worker_id!r}")

    def enabled_workers(self) -> Iterable[Worker]:
        return (worker for worker in self.workers if worker.enabled)


def _profile_name(value: object, label: str) -> str:
    name = str(value or "").strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError(f"{label} must be one profile name, not a path")
    return name


def _port(value: object, label: str) -> int:
    port = int(value)
    if not 1024 <= port <= 65535:
        raise ValueError(f"{label} must be between 1024 and 65535")
    return port


def load_registry(path: str | Path) -> Registry:
    registry_path = real(path)
    raw = json.loads(registry_path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 3:
        raise ValueError("unsupported worker registry schema")
    runtime_root = real(raw["runtime_root"])
    state_root = real(raw["state_root"])
    profile_root = real(raw["hermes_profile_root"])
    database = require_within(raw["database"], runtime_root, "database")
    seen_ids: set[str] = set()
    seen_profiles: set[str] = set()
    seen_paths: set[Path] = set()
    seen_ports: set[int] = set()
    seen_displays: set[int] = set()
    workers: list[Worker] = []
    for item in raw.get("workers", []):
        worker_id = str(item.get("id") or "").strip()
        profile = _profile_name(item.get("hermes_profile"), "Hermes profile")
        chromium = require_within(item["chromium_profile"], runtime_root, "Chromium profile")
        workspace = require_within(item["workspace"], state_root, "worker workspace")
        ports = {
            _port(item["cdp_port"], "CDP port"),
            _port(item["vnc_port"], "VNC port"),
            _port(item["novnc_port"], "noVNC port"),
        }
        if len(ports) != 3:
            raise ValueError(f"worker {worker_id!r} has duplicate ports")
        display = int(item["display"])
        if not worker_id or not 1 <= display <= 999:
            raise ValueError("worker id and a positive X display are required")
        if (
            worker_id in seen_ids or profile in seen_profiles
            or chromium in seen_paths or workspace in seen_paths
            or ports & seen_ports or display in seen_displays
        ):
            raise ValueError("worker ids, profiles, paths, displays, and ports must be unique")
        seen_ids.add(worker_id)
        seen_profiles.add(profile)
        seen_paths.update({chromium, workspace})
        seen_ports.update(ports)
        seen_displays.add(display)
        cdp_port, vnc_port, novnc_port = (
            int(item["cdp_port"]), int(item["vnc_port"]), int(item["novnc_port"]),
        )
        workers.append(Worker(
            id=worker_id, enabled=bool(item.get("enabled", False)),
            hermes_profile=profile, hermes_profile_root=profile_root,
            chromium_profile=chromium, workspace=workspace,
            cdp_port=cdp_port, display=display,
            vnc_port=vnc_port, novnc_port=novnc_port,
        ))
    if len(workers) < 2:
        raise ValueError("registry requires a non-singleton browser worker shape")
    raw_tailor = raw.get("tailor") or {}
    tailor_profile = _profile_name(raw_tailor.get("hermes_profile"), "Tailor Hermes profile")
    tailor_workspace = require_within(raw_tailor["workspace"], state_root, "Tailor workspace")
    if tailor_profile in seen_profiles or tailor_workspace in seen_paths:
        raise ValueError("Tailor profile and workspace must be unique")
    tailor = Tailor(
        id=str(raw_tailor.get("id") or "tailor"),
        hermes_profile=tailor_profile,
        hermes_profile_root=profile_root,
        workspace=tailor_workspace,
        provider=str(raw_tailor.get("provider") or ""),
        model=str(raw_tailor.get("model") or ""),
        reasoning=str(raw_tailor.get("reasoning") or ""),
    )
    return Registry(registry_path, runtime_root, state_root, database, tuple(workers), tailor)
