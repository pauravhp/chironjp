#!/usr/bin/env python3
"""Non-clobbering Chiron setup initialization and recovery ledger."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "chiron.setup-state/v1"
STAGES = (
    "canonical-data",
    "hermes-runtime",
    "provider-auth",
    "operator-vault",
    "isolated-browser",
    "remote-access",
    "photon",
    "restart-recovery",
)
PROOFS = {
    "canonical-data": "banks-validated-owner-reviewed",
    "hermes-runtime": "harmless-hermes-request",
    "provider-auth": "expected-model-request",
    "operator-vault": "vault-sentinel-inject-restart",
    "isolated-browser": "cdp-fill-reconnect",
    "remote-access": "authenticated-phone-takeover",
    "photon": "authorized-roundtrip-after-restart",
    "restart-recovery": "full-restart-behavior-suite",
}
STALE_REASONS = ("behavior-check-failed", "config-changed", "owner-requested")
CONFIG_TARGETS = {
    "config/canonical-profile-overrides.json": Path("config/canonical-profile-overrides.json"),
    "config/chiron-workers.json": Path("config/chiron-workers.json"),
}
RESUME_TARGETS = {
    "bank.template.json": Path("resume/bank.json"),
    "template.tex": Path("resume/template.tex"),
}


class StateError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def state_path(workspace: Path) -> Path:
    return workspace / ".chiron-setup" / "state.json"


def absolute_without_symlink_resolution(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def prepare_workspace(path: Path) -> Path:
    workspace = absolute_without_symlink_resolution(path)
    if workspace.is_symlink():
        raise StateError(f"workspace root must not be a symlink: {workspace}")
    if workspace.exists() and not workspace.is_dir():
        raise StateError(f"workspace root is not a directory: {workspace}")
    workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    return workspace


def confined_target(workspace: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise StateError(f"unsafe relative setup target: {relative}")
    current = workspace
    for part in relative.parent.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            current.mkdir(mode=0o700)
            mode = current.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise StateError(f"setup target ancestor must not be a symlink: {current}")
        if not stat.S_ISDIR(mode):
            raise StateError(f"setup target ancestor is not a directory: {current}")
    target = workspace / relative
    try:
        mode = target.lstat().st_mode
    except FileNotFoundError:
        return target
    if stat.S_ISLNK(mode):
        raise StateError(f"setup target must not be a symlink: {target}")
    if not stat.S_ISREG(mode):
        raise StateError(f"setup target is not a regular file: {target}")
    return target


def exclusive_copy(source: Path, target: Path) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target, flags, 0o600)
    except FileExistsError as exc:
        raise StateError(f"setup target appeared during exclusive creation: {target}") from exc
    try:
        with source.open("rb") as source_handle, os.fdopen(descriptor, "wb") as target_handle:
            descriptor = -1
            while chunk := source_handle.read(1024 * 1024):
                target_handle.write(chunk)
            target_handle.flush()
            os.fsync(target_handle.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def exclusive_write_json(path: Path, value: dict[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise StateError(f"setup state appeared during exclusive creation: {path}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def initial_state() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "stages": {stage: {"status": "pending"} for stage in STAGES},
    }


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def load_state(workspace: Path) -> dict[str, Any]:
    workspace = prepare_workspace(workspace)
    path = confined_target(workspace, Path(".chiron-setup/state.json"))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StateError(f"not initialized: {workspace}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot read state: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise StateError(f"unsupported or invalid state file: {path}")
    stages = value.get("stages")
    if not isinstance(stages, dict) or set(stages) != set(STAGES):
        raise StateError(f"state file has an unexpected stage set: {path}")
    return value


def command_init(args: argparse.Namespace) -> None:
    workspace = prepare_workspace(args.workspace)
    templates = args.templates.resolve()
    resume_assets = args.resume_assets.resolve()
    if not templates.is_dir():
        raise StateError(f"templates directory not found: {templates}")
    if not resume_assets.is_dir():
        raise StateError(f"resume assets directory not found: {resume_assets}")
    sources = [
        *((templates / source_name, relative_target) for source_name, relative_target in CONFIG_TARGETS.items()),
        *((resume_assets / source_name, relative_target) for source_name, relative_target in RESUME_TARGETS.items()),
    ]
    for source, _ in sources:
        if not source.is_file() or source.is_symlink():
            raise StateError(f"required setup source not found: {source}")
    for source, relative_target in sources:
        target = confined_target(workspace, relative_target)
        if target.exists():
            print(f"kept: {target}")
            continue
        exclusive_copy(source, target)
        print(f"created: {target}")
    path = confined_target(workspace, Path(".chiron-setup/state.json"))
    if path.exists():
        load_state(workspace)
        print(f"kept: {path}")
    else:
        exclusive_write_json(path, initial_state())
        print(f"created: {path}")


def command_status(args: argparse.Namespace) -> None:
    state = load_state(absolute_without_symlink_resolution(args.workspace))
    for stage in STAGES:
        item = state["stages"][stage]
        suffix = ""
        if item["status"] == "complete":
            suffix = f" ({item['proof']})"
        elif item["status"] in ("skipped", "stale"):
            suffix = f" ({item['reason']})"
        print(f"{stage}: {item['status']}{suffix}")


def command_mark(args: argparse.Namespace) -> None:
    workspace = prepare_workspace(args.workspace)
    state = load_state(workspace)
    expected = PROOFS[args.stage]
    if args.proof != expected:
        raise StateError(f"stage {args.stage!r} requires proof {expected!r}")
    current = state["stages"][args.stage]
    if current.get("status") == "complete" and current.get("proof") == args.proof:
        print(f"kept complete: {args.stage}")
        return
    state["stages"][args.stage] = {
        "status": "complete",
        "proof": args.proof,
        "checked_at": now(),
    }
    atomic_write(confined_target(workspace, Path(".chiron-setup/state.json")), state)
    print(f"marked complete: {args.stage}")


def command_skip(args: argparse.Namespace) -> None:
    if args.stage != "photon" or args.reason != "owner-not-selected":
        raise StateError("only photon may be skipped, with reason 'owner-not-selected'")
    workspace = prepare_workspace(args.workspace)
    state = load_state(workspace)
    state["stages"][args.stage] = {
        "status": "skipped",
        "reason": args.reason,
        "checked_at": now(),
    }
    atomic_write(confined_target(workspace, Path(".chiron-setup/state.json")), state)
    print(f"skipped: {args.stage}")


def command_stale(args: argparse.Namespace) -> None:
    workspace = prepare_workspace(args.workspace)
    state = load_state(workspace)
    state["stages"][args.stage] = {
        "status": "stale",
        "reason": args.reason,
        "checked_at": now(),
    }
    atomic_write(confined_target(workspace, Path(".chiron-setup/state.json")), state)
    print(f"marked stale: {args.stage}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init", help="copy only missing blank templates and create a ledger")
    init.add_argument("--workspace", type=Path, required=True)
    init.add_argument("--templates", type=Path, required=True)
    init.add_argument("--resume-assets", type=Path, required=True)
    init.set_defaults(func=command_init)
    status = subparsers.add_parser("status", help="show redacted stage status")
    status.add_argument("--workspace", type=Path, required=True)
    status.set_defaults(func=command_status)
    mark = subparsers.add_parser("mark", help="record one prescribed behavioral proof")
    mark.add_argument("--workspace", type=Path, required=True)
    mark.add_argument("--stage", choices=STAGES, required=True)
    mark.add_argument("--proof", choices=tuple(PROOFS.values()), required=True)
    mark.set_defaults(func=command_mark)
    skip = subparsers.add_parser("skip", help="record an owner-deselected optional stage")
    skip.add_argument("--workspace", type=Path, required=True)
    skip.add_argument("--stage", choices=STAGES, required=True)
    skip.add_argument("--reason", required=True)
    skip.set_defaults(func=command_skip)
    stale = subparsers.add_parser("stale", help="invalidate a stage whose proof no longer holds")
    stale.add_argument("--workspace", type=Path, required=True)
    stale.add_argument("--stage", choices=STAGES, required=True)
    stale.add_argument("--reason", choices=STALE_REASONS, required=True)
    stale.set_defaults(func=command_stale)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        args.func(args)
    except StateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
