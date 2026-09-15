#!/usr/bin/env python3
"""Read-only, secret-free ChironJP runtime dependency inventory."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


PYTHON_PACKAGES = {
    "browser-harness": "0.1.9",
    "browser-use": "0.13.8",
    "websockets": "15.0.1",
    "bcrypt": "5.0.0",
    "websockify": "0.13.0",
}
HERMES_VERSION = "0.20.0"
HERMES_RELEASE = "2026.8.3"
HERMES_FLAGS = (
    "--skills", "--usage-file", "--reasoning", "--oneshot",
)
TECTONIC_VERSION = "0.16.9"
POPPLER_VERSION = "26.05.0"


@dataclass(frozen=True)
class ProbeResult:
    returncode: int
    output: str


Run = Callable[[Sequence[str]], ProbeResult]
Locate = Callable[[str], str | None]


def _safe_environment(home: Path, source: dict[str, str] | None = None) -> dict[str, str]:
    """Return the minimum environment needed by metadata-only commands."""
    values = source if source is not None else os.environ
    return {
        "PATH": values.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(home),
        "HERMES_HOME": str(home / "hermes"),
        "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_CACHE_HOME": str(home / "cache"),
        "XDG_STATE_HOME": str(home / "state"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _run(command: Sequence[str]) -> ProbeResult:
    """Run metadata/help only, isolated from real homes and credential env."""
    with tempfile.TemporaryDirectory(prefix="chironjp-dependency-check-") as temporary:
        try:
            result = subprocess.run(
                list(command), cwd=temporary,
                env=_safe_environment(Path(temporary)),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ProbeResult(127, "")
    return ProbeResult(result.returncode, result.stdout[:100_000])


def _resolve(value: str | None, default: str, locate: Locate) -> str | None:
    candidate = value or default
    if os.sep in candidate:
        path = Path(candidate)
        return str(path) if path.is_file() and os.access(path, os.X_OK) else None
    return locate(candidate)


def _check(
    check_id: str,
    *,
    required: str,
    observed: str | None,
    status: str,
    detail: str,
    blocking: bool,
) -> dict[str, str | bool | None]:
    return {
        "id": check_id,
        "status": status,
        "required": required,
        "observed": observed,
        "detail": detail,
        "blocking": blocking,
        "live_proof": False,
    }


def _version(output: str, pattern: str) -> str | None:
    match = re.search(pattern, output, re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    value = match.group(1)
    return value if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,79}", value) else None


def _package_inventory(python: str, run: Run) -> tuple[str | None, dict[str, str], dict[str, bool]]:
    names = list(PYTHON_PACKAGES)
    program = (
        "import importlib.util,json,sys;from importlib.metadata import PackageNotFoundError,version;"
        f"names={names!r};values={{}};"
        "exec(\"for name in names:\\n try: values[name]=version(name)\\n except PackageNotFoundError: values[name]=None\");"
        "apis={'browser_use_module':importlib.util.find_spec('browser_use') is not None};"
        "exec(\"try:\\n import browser_harness.helpers as h\\n apis['browser_harness_helpers']=all(callable(getattr(h,n,None)) for n in ['cdp','js','fill_input','click_at_xy','current_tab','switch_tab'])\\nexcept Exception: apis['browser_harness_helpers']=False\");"
        "exec(\"try:\\n from websockets.sync.client import connect\\n apis['websockets_sync']=callable(connect)\\nexcept Exception: apis['websockets_sync']=False\");"
        "exec(\"try:\\n import bcrypt\\n apis['bcrypt_hash']=callable(getattr(bcrypt,'checkpw',None))\\nexcept Exception: apis['bcrypt_hash']=False\");"
        "exec(\"try:\\n import websockify.websocket as ws\\n apis['websockify_websocket']=all(hasattr(ws,n) for n in ['WebSocket','WebSocketWantReadError','WebSocketWantWriteError'])\\nexcept Exception: apis['websockify_websocket']=False\");"
        "print(json.dumps({'python':list(sys.version_info[:3]),'packages':values,'apis':apis},sort_keys=True))"
    )
    result = run([python, "-I", "-c", program])
    if result.returncode != 0:
        return None, {}, {}
    try:
        payload = json.loads(result.output.strip().splitlines()[-1])
        python_version = ".".join(str(value) for value in payload["python"])
        packages = {}
        for name, value in payload["packages"].items():
            rendered = str(value)
            if value is not None and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+!_-]{0,79}", rendered):
                packages[str(name)] = rendered
        apis = {str(name): value is True for name, value in payload["apis"].items()}
        return python_version, packages, apis
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, IndexError):
        return None, {}, {}


def _python_ok(version: str | None) -> bool:
    if version is None:
        return False
    try:
        major, minor = (int(value) for value in version.split(".")[:2])
    except ValueError:
        return False
    return (major, minor) >= (3, 11)


def _versioned_tool(
    check_id: str,
    executable: str | None,
    arguments: Sequence[str],
    pattern: str,
    *,
    required: str,
    tested: str | None,
    smoke_arguments: Sequence[str] | None = None,
    smoke_tokens: Sequence[str] = (),
    run: Run,
) -> dict[str, str | bool | None]:
    if executable is None:
        return _check(
            check_id, required=required, observed=None, status="missing",
            detail="executable was not found", blocking=True,
        )
    result = run([executable, *arguments])
    observed = _version(result.output, pattern)
    smoke = run([executable, *(smoke_arguments or arguments)])
    missing_tokens = [token for token in smoke_tokens if token not in smoke.output]
    surface_ok = result.returncode != 127 and smoke.returncode != 127 and not missing_tokens
    if not surface_ok:
        return _check(
            check_id, required=required, observed=observed, status="incompatible",
            detail=("required command surface is missing: " + ", ".join(missing_tokens)
                    if missing_tokens else "required command could not be executed"),
            blocking=True,
        )
    tested_match = tested is None or observed == tested
    return _check(
        check_id, required=required, observed=observed,
        status="ok" if tested_match else "untested",
        detail=("tested version and required command surface match" if tested_match else
                "required command surface is present; this version is outside the tested default"),
        blocking=False,
    )


def inventory(
    *,
    browser_python: str | None = None,
    browser_use: str | None = None,
    hermes: str | None = None,
    chromium: str | None = None,
    xvfb: str | None = None,
    x11vnc: str | None = None,
    websockify: str | None = None,
    novnc_web: str = "/usr/share/novnc",
    tectonic: str | None = None,
    pdftotext: str | None = None,
    pdftoppm: str | None = None,
    locate: Locate = shutil.which,
    run: Run = _run,
) -> dict[str, object]:
    checks: list[dict[str, str | bool | None]] = []

    selected_python = _resolve(browser_python, sys.executable, locate)
    python_version, packages, apis = _package_inventory(selected_python, run) if selected_python else (None, {}, {})
    python_ready = _python_ok(python_version)
    checks.append(_check(
        "python", required=">=3.11", observed=python_version,
        status="ok" if python_ready else ("missing" if selected_python is None else "incompatible"),
        detail="browser runtime interpreter" if python_version else "browser runtime interpreter could not be inspected",
        blocking=not python_ready,
    ))
    for name, expected in PYTHON_PACKAGES.items():
        observed = packages.get(name)
        installed = observed is not None
        checks.append(_check(
            name, required=f"tested default {expected}", observed=observed,
            status="ok" if observed == expected else ("missing" if not installed else "untested"),
            detail=("tested distribution version" if observed == expected else
                    "distribution is not installed in the selected browser interpreter" if not installed else
                    "installed version is outside the tested default; required APIs are checked separately"),
            blocking=not installed,
        ))

    adjacent_browser_use = Path(selected_python).parent / "browser-use" if selected_python else None
    browser_use_executable = (
        str(adjacent_browser_use)
        if browser_use is None and adjacent_browser_use is not None
        and adjacent_browser_use.is_file() and os.access(adjacent_browser_use, os.X_OK)
        else _resolve(browser_use, "browser-use", locate)
    )
    browser_help = run([browser_use_executable, "--help"]) if browser_use_executable else ProbeResult(127, "")
    required_apis = (
        "browser_harness_helpers", "browser_use_module", "websockets_sync",
        "bcrypt_hash", "websockify_websocket",
    )
    missing_apis = [name for name in required_apis if not apis.get(name)]
    missing_browser_flags = [flag for flag in ("--reload",) if flag not in browser_help.output]
    browser_api_ready = bool(browser_use_executable) and browser_help.returncode != 127 and not missing_apis and not missing_browser_flags
    missing_surface = (["browser-use executable"] if not browser_use_executable else []) + missing_apis + missing_browser_flags
    checks.append(_check(
        "runtime-python-api",
        required=("Browser Harness helpers, Browser Use CLI --reload, synchronous WebSocket client, "
                  "bcrypt password verification, and websockify WebSocket module"),
        observed="available" if browser_api_ready else None,
        status="ok" if browser_api_ready else "incompatible",
        detail=("focused import and CLI-help smoke passed" if browser_api_ready else
                "missing required API/command surface: " + ", ".join(missing_surface)),
        blocking=not browser_api_ready,
    ))

    hermes_executable = _resolve(hermes, "hermes", locate)
    if hermes_executable is None:
        checks.append(_check(
            "hermes", required=f"=={HERMES_VERSION} ({HERMES_RELEASE}) with required invocation flags",
            observed=None, status="missing", detail="Hermes executable was not found", blocking=True,
        ))
    else:
        version_result = run([hermes_executable, "--version"])
        help_result = run([hermes_executable, "--help"])
        # Exercise the same profile-scoped spelling used by the runtime and
        # onboarding commands without creating or opening a profile.
        profile_result = run([hermes_executable, "-p", "chironjp-dependency-probe", "--help"])
        observed_version = _version(version_result.output, r"Hermes Agent v([^\s]+)")
        observed_release = _version(version_result.output, r"Hermes Agent v[^\s]+\s+\(([^)]+)\)")
        missing_flags = [flag for flag in HERMES_FLAGS if flag not in help_result.output]
        profile_selector = (
            "Profile 'chironjp-dependency-probe' does not exist" in profile_result.output
            or "-p" in profile_result.output
        ) and "unrecognized arguments" not in profile_result.output
        if not profile_selector:
            missing_flags.append("-p")
        tested = observed_version == HERMES_VERSION and observed_release == HERMES_RELEASE
        surface_ready = version_result.returncode != 127 and help_result.returncode != 127 and not missing_flags
        observed = (
            f"{observed_version} ({observed_release})"
            if observed_version and observed_release else observed_version
        )
        checks.append(_check(
            "hermes", required=f"tested default {HERMES_VERSION} ({HERMES_RELEASE}); flags: " + ", ".join((*HERMES_FLAGS, "-p")),
            observed=observed,
            status=("incompatible" if not surface_ready else "ok" if tested else "untested"),
            detail=("required stock CLI flags are missing: " + ", ".join(missing_flags)
                    if missing_flags else "tested stock CLI and invocation surface match" if tested else
                    "required stock CLI surface is present; this version is outside the tested default"),
            blocking=not surface_ready,
        ))

    chromium_executable = _resolve(chromium, "chromium", locate) or _resolve(chromium, "chromium-browser", locate)
    checks.append(_versioned_tool(
        "chromium", chromium_executable, ["--version"], r"Chromium\s+([^\s]+)",
        required="installed; current supported security release", tested=None, run=run,
    ))

    for check_id, value, default, args, pattern in (
        ("xvfb", xvfb, "Xvfb", ["-help"], r"X\.Org X Server\s+([^\s]+)"),
        ("x11vnc", x11vnc, "x11vnc", ["-version"], r"x11vnc:\s+([^\s]+)"),
        ("websockify-cli", websockify, "websockify", ["--help"], r"websockify(?:\.py)?\s+v?(\d+(?:\.\d+)+)"),
    ):
        executable = _resolve(value, default, locate)
        if executable is None:
            checks.append(_check(
                check_id, required="installed", observed=None, status="missing",
                detail="executable was not found", blocking=True,
            ))
            continue
        result = run([executable, *args])
        observed = _version(result.output, pattern)
        executable_ready = result.returncode != 127 and bool(result.output)
        checks.append(_check(
            check_id, required="installed", observed=observed or "available",
            status="ok" if executable_ready else "incompatible",
            detail="executable help/version smoke passed; distribution revision is inventory only",
            blocking=not executable_ready,
        ))

    novnc_root = Path(novnc_web)
    novnc_ready = (
        novnc_root.is_dir()
        and (novnc_root / "vnc.html").is_file()
        and (novnc_root / "core" / "rfb.js").is_file()
    )
    checks.append(_check(
        "novnc-assets", required="web root containing vnc.html and core/rfb.js", observed="available" if novnc_ready else None,
        status="ok" if novnc_ready else "missing",
        detail="asset existence only; authentication and transport are not exercised",
        blocking=not novnc_ready,
    ))

    tectonic_executable = _resolve(tectonic, "tectonic", locate)
    checks.append(_versioned_tool(
        "tectonic", tectonic_executable, ["--version"], r"Tectonic\s+([^\s]+)",
        required=f"tested default {TECTONIC_VERSION}; input and --outdir CLI",
        tested=TECTONIC_VERSION, smoke_arguments=["--help"], smoke_tokens=["<INPUT>", "--outdir"], run=run,
    ))
    for check_id, value, default in (
        ("pdftotext", pdftotext, "pdftotext"), ("pdftoppm", pdftoppm, "pdftoppm"),
    ):
        executable = _resolve(value, default, locate)
        smoke_tokens = ["-bbox-layout"] if check_id == "pdftotext" else ["-png", "-r"]
        checks.append(_versioned_tool(
            check_id, executable, ["-v"], rf"{check_id}\s+version\s+([^\s]+)",
            required=f"Poppler tested default {POPPLER_VERSION}", tested=POPPLER_VERSION,
            smoke_arguments=["-h"], smoke_tokens=smoke_tokens, run=run,
        ))

    ok = not any(check["blocking"] for check in checks)
    return {
        "schema_version": 1,
        "ok": ok,
        "proof": "installed_surface_smoke_only",
        "secret_free": True,
        "checks": checks,
        "limitations": [
            "No profile, credential, browser state, network login, render, or final action was inspected.",
            "Import/help smoke is not live behavioral proof; run the repository's isolated proofs separately.",
        ],
    }


def _text(report: dict[str, object]) -> str:
    warnings = any(check["status"] == "untested" for check in report["checks"])  # type: ignore[union-attr]
    heading = "READY WITH UNTESTED VERSIONS" if report["ok"] and warnings else "READY" if report["ok"] else "NOT READY"
    lines = ["ChironJP runtime dependencies: " + heading]
    for check in report["checks"]:  # type: ignore[union-attr]
        observed = check["observed"] or "not found"
        lines.append(f"[{str(check['status']).upper():10}] {check['id']}: {observed} (required {check['required']})")
    lines.append("Surface smoke only: no live browser, profile, credential, render, or delivery proof was performed.")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-python")
    parser.add_argument("--browser-use")
    parser.add_argument("--hermes")
    parser.add_argument("--chromium")
    parser.add_argument("--xvfb")
    parser.add_argument("--x11vnc")
    parser.add_argument("--websockify")
    parser.add_argument("--novnc-web", default="/usr/share/novnc")
    parser.add_argument("--tectonic")
    parser.add_argument("--pdftotext")
    parser.add_argument("--pdftoppm")
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args(argv)
    report = inventory(
        browser_python=arguments.browser_python, browser_use=arguments.browser_use,
        hermes=arguments.hermes,
        chromium=arguments.chromium, xvfb=arguments.xvfb, x11vnc=arguments.x11vnc,
        websockify=arguments.websockify, novnc_web=arguments.novnc_web,
        tectonic=arguments.tectonic, pdftotext=arguments.pdftotext,
        pdftoppm=arguments.pdftoppm,
    )
    print(json.dumps(report, indent=2, sort_keys=True) if arguments.json else _text(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
