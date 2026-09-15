"""Immutable request/artifact control adapted from Chiron's proven Tailor path."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from .paths import private_dir, private_file, require_within
from .registry import Registry
from .resume import render_agent_manifest, tailor_contract
from .runtime import hermes_cli
from .store import Store, compact_json, file_sha256, iso


TAILOR_PROMPT = """Own the single resume request in $CHIRONJP_TAILOR_WORKSPACE/tailor-brief.json.
Use the chiron-resume-tailor skill. Select only canonical bank IDs and prose, write the
manifest, render and materially repair every deterministic failure, then inspect the
exact passing PNG with vision. Bind that exact inspection and finish the request. Never
use a browser, change canonical facts, invent a claim, or operate an employer form."""


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(compact_json(value).encode()).hexdigest()


def ensure_source_request(
    store: Store,
    *,
    source_row_id: int,
    profile_path: str | Path,
    bank_path: str | Path,
    template_path: str | Path,
) -> Mapping[str, Any]:
    profile = Path(profile_path).expanduser().resolve(strict=True)
    bank = Path(bank_path).expanduser().resolve(strict=True)
    template = Path(template_path).expanduser().resolve(strict=True)
    with closing(store.connect()) as connection:
        source = connection.execute("SELECT * FROM source_jobs WHERE id=?", (source_row_id,)).fetchone()
    if source is None:
        raise ValueError("unknown source row")
    identity = {
        "contract_version": 1,
        "source_row_id": int(source["id"]),
        "content_hash": str(source["content_hash"]),
        "role": str(source["role"]),
        "description_sha256": hashlib.sha256(str(source["description"]).encode()).hexdigest(),
        "profile_sha256": file_sha256(profile),
        "bank_sha256": file_sha256(bank),
        "template_sha256": file_sha256(template),
    }
    request_key = _digest(identity)
    request_id = "trq_" + request_key[:24]
    with store.immediate() as connection:
        connection.execute(
            """INSERT OR IGNORE INTO tailor_requests(
               id,request_key,source_row_id,role,description,profile_path,profile_sha256,
               bank_path,bank_sha256,template_path,template_sha256,created_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                request_id, request_key, source["id"], source["role"], source["description"],
                str(profile), identity["profile_sha256"], str(bank), identity["bank_sha256"], str(template),
                identity["template_sha256"], iso(),
            ),
        )
        return dict(connection.execute(
            "SELECT * FROM tailor_requests WHERE request_key=?", (request_key,),
        ).fetchone())


def _request(store: Store, request_id: str) -> Mapping[str, Any]:
    with closing(store.connect()) as connection:
        row = connection.execute("SELECT * FROM tailor_requests WHERE id=?", (request_id,)).fetchone()
    if row is None:
        raise ValueError("unknown Tailor request")
    return dict(row)


def _request_workspace(registry: Registry, request_id: str) -> Path:
    return require_within(
        registry.tailor.workspace / "attempts" / request_id,
        registry.tailor.workspace,
        "Tailor request workspace",
    )


def write_brief(store: Store, registry: Registry, request_id: str) -> Path:
    request = _request(store, request_id)
    workspace = _request_workspace(registry, request_id)
    private_dir(workspace)
    manifest = workspace / "selection.json"
    validation = workspace / "latest-validation.json"
    visual = workspace / "visual-inspection.json"
    brief = {
        "contract": "chironjp-tailor-v1",
        "request_id": request_id,
        "role": request["role"],
        "job_description": request["description"],
        "canonical_choices": tailor_contract(
            role=request["role"], description=request["description"],
            profile_path=request["profile_path"], bank_path=request["bank_path"],
            template_path=request["template_path"],
        ),
        "manifest_path": str(manifest),
        "render_argv": [
            "chironctl", "tailor-render", "--database", str(registry.database),
            "--registry", str(registry.path), "--request", request_id,
            "--manifest", str(manifest), "--workspace", str(workspace),
        ],
        "visual_inspection_path": str(visual),
        "finish_argv": [
            "chironctl", "tailor-finish", "--database", str(registry.database),
            "--registry", str(registry.path), "--request", request_id,
            "--validation", str(validation), "--visual-inspection", str(visual),
        ],
        "production_selector": "agent_only",
        "diagnostic_python_fallback_allowed": False,
    }
    path = workspace / "tailor-brief.json"
    path.write_text(json.dumps(brief, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    private_file(path)
    return workspace


def render_request(
    store: Store,
    registry: Registry,
    *,
    request_id: str,
    selection_path: str | Path,
    workspace: str | Path,
) -> Mapping[str, Any]:
    if os.environ.get("CHIRONJP_TAILOR_REQUEST_ID") not in {None, "", request_id}:
        raise ValueError("Tailor render request does not match the active invocation")
    root = require_within(workspace, registry.tailor.workspace, "Tailor workspace")
    expected_root = _request_workspace(registry, request_id)
    if root != expected_root:
        raise ValueError("Tailor workspace does not match the immutable request")
    selection = require_within(selection_path, root, "Tailor manifest")
    request = _request(store, request_id)
    if file_sha256(request["profile_path"]) != request["profile_sha256"]:
        raise ValueError("canonical profile changed after the immutable request")
    if file_sha256(request["bank_path"]) != request["bank_sha256"]:
        raise ValueError("canonical bank changed after the immutable request")
    if file_sha256(request["template_path"]) != request["template_sha256"]:
        raise ValueError("resume template changed after the immutable request")
    result = dict(render_agent_manifest(
        selection_path=selection,
        role=request["role"], description=request["description"],
        output_dir=root, profile_path=request["profile_path"],
        bank_path=request["bank_path"], template_path=request["template_path"],
    ))
    latest = root / "latest-validation.json"
    latest.write_text(compact_json(result) + "\n", encoding="utf-8")
    private_file(latest)
    return {**result, "latest_validation_path": str(latest)}


def _exact_file(path: Any, expected_hash: Any, root: Path, label: str) -> Path:
    value = require_within(str(path), root, label)
    if not value.is_file() or file_sha256(value) != str(expected_hash):
        raise ValueError(f"{label} is missing or changed")
    return value


def finish_request(
    store: Store,
    registry: Registry,
    *,
    request_id: str,
    validation_path: str | Path,
    visual_inspection_path: str | Path,
) -> Mapping[str, Any]:
    if os.environ.get("CHIRONJP_TAILOR_REQUEST_ID") not in {None, "", request_id}:
        raise ValueError("Tailor finish request does not match the active invocation")
    root = _request_workspace(registry, request_id)
    validation_file = require_within(validation_path, root, "Tailor validation")
    visual_file = require_within(visual_inspection_path, root, "Tailor visual inspection")
    if validation_file != root / "latest-validation.json":
        raise ValueError("Tailor validation does not match the immutable request workspace")
    if visual_file != root / "visual-inspection.json":
        raise ValueError("Tailor visual inspection does not match the immutable request workspace")
    validation = json.loads(validation_file.read_text(encoding="utf-8"))
    visual = json.loads(visual_file.read_text(encoding="utf-8"))
    if validation.get("passed") is not True or validation.get("errors"):
        raise ValueError("deterministic resume validation did not pass")
    expected_visual = {
        "schema_version": 1,
        "passed": True,
        "obvious_defects": [],
        "selection_sha256": validation.get("selection_sha256"),
        "preview_sha256": validation.get("preview_sha256"),
        "inspected_preview_path": validation.get("preview_path"),
    }
    if any(visual.get(key) != value for key, value in expected_visual.items()):
        raise ValueError("visual inspection does not prove the exact passing preview")
    request = _request(store, request_id)
    bindings = {
        "profile_sha256": request["profile_sha256"],
        "bank_sha256": request["bank_sha256"],
        "template_sha256": request["template_sha256"],
    }
    if any(validation.get(key) != value for key, value in bindings.items()):
        raise ValueError("Tailor validation assets do not match the immutable request")
    source = _exact_file(validation["source_path"], validation["source_sha256"], root, "tailored source")
    resume = _exact_file(validation["resume_path"], validation["resume_sha256"], root, "tailored resume")
    selection = _exact_file(validation["selection_path"], validation["selection_sha256"], root, "tailored selection")
    preview = _exact_file(validation["preview_path"], validation["preview_sha256"], root, "tailored preview")
    normalized = json.loads(selection.read_text(encoding="utf-8"))
    expected_selection = {
        **bindings,
        "role": request["role"],
        "job_description_sha256": hashlib.sha256(str(request["description"]).encode()).hexdigest(),
    }
    if any(normalized.get(key) != value for key, value in expected_selection.items()):
        raise ValueError("Tailor selection does not match the immutable request")
    generation_key = _digest({
        "request_key": request["request_key"],
        "selection_sha256": validation["selection_sha256"],
        "resume_sha256": validation["resume_sha256"],
        "preview_sha256": validation["preview_sha256"],
    })
    artifact_id = "tgen_" + generation_key[:24]
    destination = registry.runtime_root / "tailored" / request_id / artifact_id
    private_dir(destination)
    names = {
        source: "resume.tex", resume: "tailored-resume.pdf", selection: "selection.json",
        validation_file: "validation.json", preview: "preview.png", visual_file: "visual-inspection.json",
    }
    copied: dict[str, Path] = {}
    for original, name in names.items():
        target = destination / name
        if target.exists() and file_sha256(target) != file_sha256(original):
            raise ValueError("immutable tailored artifact path collision")
        if not target.exists():
            shutil.copy2(original, target)
            private_file(target)
        copied[name] = target
    artifact = {
        "id": artifact_id, "request_id": request_id, "generation_key": generation_key,
        "resume_path": str(copied["tailored-resume.pdf"]),
        "resume_sha256": file_sha256(copied["tailored-resume.pdf"]),
        "source_path": str(copied["resume.tex"]),
        "source_sha256": file_sha256(copied["resume.tex"]),
        "selection_path": str(copied["selection.json"]),
        "selection_sha256": file_sha256(copied["selection.json"]),
        "validation_path": str(copied["validation.json"]),
        "validation_sha256": file_sha256(copied["validation.json"]),
        "preview_path": str(copied["preview.png"]),
        "preview_sha256": file_sha256(copied["preview.png"]),
        "visual_inspection_json": compact_json(visual), "created_at": iso(),
    }
    with store.immediate() as connection:
        existing = connection.execute(
            "SELECT * FROM tailored_artifacts WHERE request_id=?", (request_id,),
        ).fetchone()
        if existing is not None:
            return dict(existing)
        connection.execute(
            """INSERT INTO tailored_artifacts(
               id,request_id,generation_key,resume_path,resume_sha256,source_path,source_sha256,
               selection_path,selection_sha256,validation_path,validation_sha256,preview_path,
               preview_sha256,visual_inspection_json,created_at
               ) VALUES (:id,:request_id,:generation_key,:resume_path,:resume_sha256,:source_path,
               :source_sha256,:selection_path,:selection_sha256,:validation_path,:validation_sha256,
               :preview_path,:preview_sha256,:visual_inspection_json,:created_at)""",
            artifact,
        )
    return artifact


def admit_package(store: Store, *, source_row_id: int, artifact_id: str) -> Mapping[str, Any]:
    """Bind one exact, visually inspected artifact before browser assignment."""
    with store.immediate() as connection:
        row = connection.execute(
            """SELECT s.*,a.*,r.request_key FROM source_jobs s
               JOIN tailor_requests r ON r.source_row_id=s.id
               JOIN tailored_artifacts a ON a.request_id=r.id
               WHERE s.id=? AND a.id=?""", (source_row_id, artifact_id),
        ).fetchone()
        if row is None:
            raise ValueError("source and tailored artifact are not an exact request pair")
        identity = str(row["official_apply_identity"] or f"{row['source_name']}:{row['source_job_id']}")
        application_id = "app_" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        package_id = "pkg_" + hashlib.sha256(
            f"{application_id}:{row['resume_sha256']}".encode()
        ).hexdigest()[:24]
        start_url = str(row["resolver_url"] or row["source_url"])
        host = urlsplit(start_url).hostname or ""
        connection.execute(
            """INSERT OR IGNORE INTO applications(
               id,source_row_id,start_url,tenant_host,created_at
               ) VALUES (?,?,?,?,?)""",
            (application_id, source_row_id, start_url, host, iso()),
        )
        connection.execute(
            """INSERT OR IGNORE INTO packages(
               id,application_id,resume_path,resume_sha256,source_path,source_sha256,
               manifest_path,manifest_sha256,validation_path,validation_sha256,
               preview_path,preview_sha256,visual_inspection_json,created_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                package_id, application_id, row["resume_path"], row["resume_sha256"],
                row["source_path"], row["source_sha256"], row["selection_path"],
                row["selection_sha256"], row["validation_path"], row["validation_sha256"],
                row["preview_path"], row["preview_sha256"], row["visual_inspection_json"], iso(),
            ),
        )
        connection.execute(
            "UPDATE source_jobs SET disposition='assigned',application_id=?,updated_at=? WHERE id=?",
            (application_id, iso(), source_row_id),
        )
        return dict(connection.execute("SELECT * FROM packages WHERE id=?", (package_id,)).fetchone())


def run_one(store: Store, registry: Registry, request_id: str, *, timeout_seconds: int = 2100) -> Mapping[str, Any]:
    """Invoke the configured non-browser Hermes Tailor for one immutable request."""
    request = _request(store, request_id)
    with closing(store.connect()) as connection:
        existing = connection.execute(
            "SELECT * FROM tailored_artifacts WHERE request_id=?", (request_id,),
        ).fetchone()
    if existing is not None:
        return {"state": "ready", "artifact": dict(existing), "duplicate": True}
    workspace = write_brief(store, registry, request_id)
    usage_path = workspace / "usage.json"
    command = [
        hermes_cli(), "-p", registry.tailor.hermes_profile,
        "--model", registry.tailor.model, "--provider", registry.tailor.provider,
        "--reasoning", registry.tailor.reasoning,
        "--skills", "chiron-resume-tailor", "--usage-file", str(usage_path),
        "--oneshot", TAILOR_PROMPT,
    ]
    started = iso()
    began = time.monotonic()
    try:
        result = subprocess.run(
            command, cwd=Path(__file__).resolve().parents[1],
            env={
                **os.environ,
                # Bind both the selector and process environment to this
                # registry's exact profile. This prevents a sticky/default
                # profile from receiving Tailor state.
                "HERMES_HOME": str(registry.tailor.hermes_home),
                "CHIRONJP_TAILOR_WORKSPACE": str(workspace),
                "CHIRONJP_TAILOR_REQUEST_ID": request_id,
            },
            timeout=timeout_seconds, check=False,
        )
        return_code = int(result.returncode)
    except subprocess.TimeoutExpired:
        return_code = 124
    with closing(store.connect()) as connection:
        artifact_row = connection.execute(
            "SELECT * FROM tailored_artifacts WHERE request_id=?", (request_id,),
        ).fetchone()
    artifact = dict(artifact_row) if artifact_row else None
    evidence = {"artifact_id": artifact.get("id") if artifact else None,
                "elapsed_seconds": round(time.monotonic() - began, 3)}
    usage: Mapping[str, Any] = {}
    if usage_path.is_file():
        try:
            candidate = json.loads(usage_path.read_text(encoding="utf-8"))
            usage = candidate if isinstance(candidate, Mapping) else {}
        except json.JSONDecodeError:
            pass
    attempt_id = "tat_" + hashlib.sha256(f"{request_id}:{started}".encode()).hexdigest()[:24]
    with store.immediate() as connection:
        connection.execute(
            """INSERT INTO tailor_attempts(
               id,request_id,started_at,ended_at,return_code,workspace_path,usage_json,evidence_json
               ) VALUES (?,?,?,?,?,?,?,?)""",
            (attempt_id, request_id, started, iso(), return_code, str(workspace),
             compact_json(usage), compact_json(evidence)),
        )
    return {"state": "ready" if artifact else "unfulfilled", "request": request,
            "return_code": return_code, "artifact": artifact, "workspace": str(workspace)}
