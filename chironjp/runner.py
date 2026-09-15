"""One-package Hermes browser runner adapted from Chiron's retained-Review path."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from . import browser_tools
from .paths import REPO_ROOT, private_dir, private_file
from .registry import Registry, Worker
from .runtime import hermes_cli, start_chromium
from .store import Store, file_sha256


WORKER_PROVIDER = "nous"
WORKER_MODEL = "z-ai/glm-5.3-flash"
WORKER_REASONING = "high"

RUN_PROMPT = """Own the one browser-preparation request in
$BH_AGENT_WORKSPACE/run-brief.json. Use chiron-application-executor and the
copied agent_helpers.py. Prepare the exact retained target to guarded Review;
invoke the browser runtime only through $CHIRONJP_BROWSER_HARNESS and preserve
the supplied BU_NAME. Never activate a final action. Write review.json with only the documented
fields, then execute finish_argv as an argv array without a shell. Exit while
leaving Chromium and the exact application target open."""


def _workspace(worker: Worker, attempt_id: str) -> Path:
    root = worker.workspace / "attempts" / attempt_id
    private_dir(root)
    return root


def _browser_daemon_name(worker_id: str, application_id: str, attempt_id: str) -> str:
    identity = f"{worker_id}:{application_id}:{attempt_id}".encode("utf-8")
    return "chironjp_" + hashlib.sha256(identity).hexdigest()[:32]


def prepare_workspace(store: Store, registry: Registry, attempt_id: str) -> Path:
    context = store.attempt_context(attempt_id)
    worker = registry.worker(str(context["worker_id"]))
    workspace = _workspace(worker, attempt_id)
    helper = workspace / "agent_helpers.py"
    if helper.exists() and file_sha256(helper) != file_sha256(REPO_ROOT / "chironjp/browser_tools.py"):
        raise ValueError("attempt helper path already contains different code")
    if not helper.exists():
        shutil.copy2(REPO_ROOT / "chironjp/browser_tools.py", helper)
        private_file(helper)
    profile_path = Path(str(context["profile_path"])).resolve(strict=True)
    if file_sha256(profile_path) != context["profile_sha256"]:
        raise ValueError("canonical profile changed after package admission")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    review_file = workspace / "review.json"
    daemon_name = _browser_daemon_name(worker.id, str(context["application_id"]), attempt_id)
    browser_bin = registry.runtime_root / "browser-venv" / "bin"
    brief = {
        "contract": "chironjp-browser-run-v1",
        "attempt_id": attempt_id,
        "application_id": context["application_id"],
        "worker_id": worker.id,
        "profile_name": worker.hermes_profile,
        "cdp_url": worker.cdp_url,
        "start_url": context["start_url"],
        "ats_family": context["ats_family"],
        "company": context["company"],
        "role": context["role"],
        "job_description": context["description"],
        "browser_runtime": {
            "browser_harness": str(browser_bin / "browser-harness"),
            "browser_use": str(browser_bin / "browser-use"),
            "daemon_name": daemon_name,
        },
        "canonical_profile": profile,
        "package": {
            "resume_path": context["resume_path"],
            "resume_sha256": context["resume_sha256"],
            "manifest_path": context["manifest_path"],
            "manifest_sha256": context["manifest_sha256"],
        },
        "review_path": str(review_file),
        "review_contract": {
            "schema": "chironjp-review-v1",
            "top_level_keys": [
                "stage", "url", "target_id", "observed_resume_sha256", "rendered",
                "provisional", "final_actions", "submit_untouched", "final_guard_active",
            ],
            "constants": {
                "stage": "review", "submit_untouched": True,
                "final_guard_active": True,
            },
            "types": {
                "url": "string", "target_id": "string",
                "observed_resume_sha256": "sha256", "rendered": "object",
                "provisional": "array", "final_actions": "array",
            },
            "controller_derived": [
                "application_identity", "ats_family", "employer_constraints",
                "rendered_readback",
            ],
        },
        "finish_argv": [
            "chironctl", "finish-review", "--database", str(registry.database),
            "--registry", str(registry.path), "--attempt", attempt_id,
            "--review-file", str(review_file),
        ],
        "final_action_authorized": False,
    }
    path = workspace / "run-brief.json"
    path.write_text(json.dumps(brief, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    private_file(path)
    return workspace


class _CDP:
    def __init__(self, websocket_url: str):
        try:
            from websockets.sync.client import connect
        except ImportError as exc:
            raise RuntimeError("Review verification requires websockets==15.0.1") from exc
        self.socket = connect(websocket_url, max_size=24 * 1024 * 1024)
        self.sequence = 0

    def close(self) -> None:
        self.socket.close()

    def evaluate(self, expression: str) -> Any:
        self.sequence += 1
        sequence = self.sequence
        self.socket.send(json.dumps({
            "id": sequence, "method": "Runtime.evaluate",
            "params": {
                "expression": expression, "returnByValue": True,
                "awaitPromise": True, "includeCommandLineAPI": True,
            },
        }))
        while True:
            reply = json.loads(self.socket.recv(timeout=10))
            if reply.get("id") != sequence:
                continue
            if "error" in reply or reply.get("result", {}).get("exceptionDetails"):
                raise RuntimeError("retained Review readback failed")
            return reply["result"]["result"].get("value")


def _target(worker: Worker, target_id: str) -> Mapping[str, Any]:
    targets = json.load(urlopen(worker.cdp_url + "/json/list", timeout=3))
    target = next(
        (item for item in targets if item.get("id") == target_id and item.get("type") == "page"),
        None,
    )
    if target is None:
        raise ValueError("Review target is not retained by the assigned worker")
    return target


def _infer_ats_family(url: str) -> str:
    host = str(urlsplit(url).hostname or "").casefold().rstrip(".")
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        return "greenhouse"
    if host.endswith(".myworkdayjobs.com"):
        return "workday"
    return "unknown"


def _create_application_target(worker: Worker, start_url: str) -> Mapping[str, Any]:
    """Create one new page at the exact admitted URL through Chromium's CDP edge."""
    request = Request(
        worker.cdp_url + "/json/new?" + quote(start_url, safe=""),
        method="PUT",
    )
    created = json.load(urlopen(request, timeout=3))
    if (
        not isinstance(created, Mapping)
        or created.get("type") != "page"
        or not str(created.get("id") or "")
    ):
        raise RuntimeError("Chromium did not create the exact application target")
    return created


def _ensure_application_target(
    store: Store, worker: Worker, context: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Create the attempt target once, or resume only its persisted exact id."""
    attempt_id = str(context["attempt_id"])
    target_id = str(context.get("designated_target_id") or "")
    if target_id:
        target = _target(worker, target_id)
    else:
        retry_target_id = str(context.get("retry_target_id") or "")
        retry_start_url = str(context.get("retry_start_url") or "")
        target = None
        if retry_target_id and retry_start_url == str(context["start_url"]):
            try:
                target = _target(worker, retry_target_id)
            except ValueError:
                target = None
        if target is None:
            target = _create_application_target(worker, str(context["start_url"]))
        target_id = str(target["id"])
        store.bind_attempt_target(
            attempt_id, worker_id=worker.id, target_id=target_id,
            start_url=str(context["start_url"]),
        )
    # Follow only this exact page id while a normal official Apply redirect settles.
    prior_url = ""
    stable_observations = 0
    for _ in range(50):
        target = _target(worker, target_id)
        current_url = str(target.get("url") or "")
        if urlsplit(current_url).scheme in {"http", "https"}:
            stable_observations = stable_observations + 1 if current_url == prior_url else 1
            prior_url = current_url
            if _infer_ats_family(current_url) != "unknown" or stable_observations >= 10:
                break
        time.sleep(0.1)
    else:
        raise RuntimeError("designated Chromium target did not reach an HTTP(S) page")
    store.observe_attempt_target(
        attempt_id, target_id=target_id, url=current_url,
        ats_family=_infer_ats_family(current_url),
    )
    return target


_IDENTITY_JS = r"""(() => ({
  url: location.href,
  title: String(document.title || '').slice(0, 500),
  heading: String(document.querySelector('h1,[role="heading"]')?.textContent || '').slice(0, 1000),
  body: String(document.body?.innerText || '').replace(/\s+/g,' ').trim().slice(0, 20000)
}))()"""

_EMPLOYER_CONSTRAINTS_JS = r"""(() => {
  const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
  const qualifies = text => {
    const value = norm(text).toLowerCase();
    return value.includes('most recent school or university') && value.includes('add only');
  };
  const candidates = Array.from(document.querySelectorAll('p,li,div,span,label'))
    .map(element => norm(element.innerText || element.textContent))
    .filter(text => text && text.length <= 2000 && qualifies(text))
    .sort((left, right) => left.length - right.length);
  if (!candidates.length) return {};
  return {education: {
    kind: 'most_recent_only', limit: 1, rendered_instruction: candidates[0]
  }};
})()"""


def _normalized_identity_text(value: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split())


def _known_apply_identity(url: str) -> str | None:
    parsed = urlsplit(url)
    host = str(parsed.hostname or "").casefold()
    parts = [part.casefold() for part in parsed.path.split("/") if part]
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and "jobs" in parts:
        index = parts.index("jobs")
        if index > 0 and index + 1 < len(parts):
            return f"greenhouse:{parts[index - 1]}:{parts[index + 1]}"
    if host == "jobs.ashbyhq.com" and len(parts) >= 2:
        return f"ashby:{parts[0]}:{parts[1]}"
    if host in {"jobs.lever.co", "apply.lever.co"} and len(parts) >= 2:
        return f"lever:{parts[0]}:{parts[1]}"
    if host.endswith(".myworkdayjobs.com") and "job" in parts:
        job_index = parts.index("job")
        tail = parts[job_index + 1:]
        if "apply" in tail:
            tail = tail[:tail.index("apply")]
        if tail:
            return f"workday:{host}:{tail[-1]}"
    return None


def _verify_application_identity(
    context: Mapping[str, Any], target_url: str, snapshot: Mapping[str, Any],
) -> None:
    """Verify redirect lineage by admitted requisition or rendered employer/role."""
    start_host = urlsplit(str(context["start_url"])).hostname
    target_host = urlsplit(target_url).hostname
    if not target_host:
        raise ValueError("Review target has no HTTP application identity")
    official_identity = str(context.get("official_apply_identity") or "")
    observed_identity = _known_apply_identity(target_url)
    expected_identity = (
        official_identity
        if official_identity.startswith(("greenhouse:", "ashby:", "lever:", "workday:"))
        else _known_apply_identity(str(context["start_url"]))
    )
    if observed_identity and expected_identity == observed_identity:
        return
    if expected_identity and observed_identity and observed_identity != expected_identity:
        raise ValueError("Review target does not match the admitted official requisition")
    if target_host == start_host and not expected_identity:
        return
    rendered = _normalized_identity_text(" ".join(
        str(snapshot.get(key) or "") for key in ("title", "heading", "body")
    ))
    company = _normalized_identity_text(context.get("company"))
    role = _normalized_identity_text(context.get("role"))
    padded = f" {rendered} "
    if (
        not company or not role
        or f" {company} " not in padded
        or f" {role} " not in padded
    ):
        raise ValueError(
            "cross-host Review did not prove the admitted employer and requisition role"
        )


def _validated_employer_constraints(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not value:
        return {}
    if set(value) != {"education"} or not isinstance(value["education"], Mapping):
        raise ValueError("controller employer constraint has an unexpected shape")
    education = value["education"]
    instruction = " ".join(str(education.get("rendered_instruction") or "").split())
    normalized = instruction.casefold()
    if (
        set(education) != {"kind", "limit", "rendered_instruction"}
        or education.get("kind") != "most_recent_only"
        or education.get("limit") != 1
        or len(instruction) > 2000
        or "most recent school or university" not in normalized
        or "add only" not in normalized
    ):
        raise ValueError("controller could not prove the rendered employer constraint")
    return {"education": {
        "kind": "most_recent_only", "limit": 1,
        "rendered_instruction": instruction,
    }}


def finish_review(
    store: Store, registry: Registry, *, attempt_id: str, review_path: str | Path,
) -> Mapping[str, Any]:
    """Independently read the exact live target before durable publication."""
    context = store.attempt_context(attempt_id)
    if context["attempt_status"] != "running":
        raise ValueError("Review attempt is not running")
    worker = registry.worker(str(context["worker_id"]))
    workspace = _workspace(worker, attempt_id)
    review_file = Path(review_path).resolve(strict=True)
    if review_file != workspace / "review.json":
        raise ValueError("Review artifact is outside its exact attempt workspace")
    artifact = json.loads(review_file.read_text(encoding="utf-8"))
    if not isinstance(artifact, Mapping):
        raise ValueError("Review artifact must be an object")
    target_id = str(artifact.get("target_id") or "")
    if target_id != str(context.get("designated_target_id") or ""):
        raise ValueError("Review artifact is not for the attempt's designated target")
    target = _target(worker, target_id)
    if str(target.get("url") or "") != str(artifact.get("url") or ""):
        raise ValueError("Review URL does not match the exact retained target")
    profile_path = Path(str(context["profile_path"])).resolve(strict=True)
    if file_sha256(profile_path) != context["profile_sha256"]:
        raise ValueError("canonical profile changed after package admission")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    client = _CDP(str(target["webSocketDebuggerUrl"]))
    try:
        identity = client.evaluate(_IDENTITY_JS) or {}
        if not isinstance(identity, Mapping) or str(identity.get("url") or "") != str(target["url"]):
            raise ValueError("controller could not bind the exact application identity")
        _verify_application_identity(context, str(target["url"]), identity)
        ats_family = _infer_ats_family(str(target["url"]))
        if ats_family == "unknown":
            ats_family = str(context.get("ats_family") or "unknown")
        store.observe_attempt_target(
            attempt_id, target_id=target_id, url=str(target["url"]),
            ats_family=ats_family,
        )
        constraints = (
            _validated_employer_constraints(client.evaluate(_EMPLOYER_CONSTRAINTS_JS) or {})
            if ats_family == "workday" else {}
        )
        observed = browser_tools.review_readback(
            client.evaluate, ats_family, profile, constraints=constraints,
        )
    finally:
        client.close()
    if observed.get("stage") != "review" or observed.get("final_guard_active") is not True:
        raise ValueError("controller readback did not prove guarded Review")
    if observed.get("submit_untouched") is not True:
        raise ValueError("controller readback did not prove an untouched final action")
    if str(observed.get("url")) != str(artifact.get("url")):
        raise ValueError("controller Review URL differs from the worker artifact")
    if list(observed.get("final_actions") or []) != list(artifact.get("final_actions") or []):
        raise ValueError("controller final-action readback differs from the worker artifact")
    bound = dict(artifact)
    bound["rendered"] = observed
    bound["final_guard_active"] = True
    bound["submit_untouched"] = True
    return store.publish_review(
        attempt_id, bound, profile_name=worker.hermes_profile,
    )


def run_attempt(
    store: Store, registry: Registry, attempt_id: str, *, timeout_seconds: int = 2100,
) -> Mapping[str, Any]:
    context = store.attempt_context(attempt_id)
    if context["attempt_status"] != "running":
        raise ValueError("browser attempt is not running")
    worker = registry.worker(str(context["worker_id"]))
    try:
        start_chromium(registry, worker, initial_url="about:blank")
        target = _ensure_application_target(store, worker, context)
        target_id = str(target["id"])
        context = store.attempt_context(attempt_id)
        workspace = prepare_workspace(store, registry, attempt_id)
    except Exception as exc:
        store.fail_attempt(
            attempt_id, code="browser_start_failed",
            detail=f"{type(exc).__name__}: {exc}",
        )
        raise
    brief_path = workspace / "run-brief.json"
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    brief["target_id"] = target_id
    brief_path.write_text(json.dumps(brief, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    private_file(brief_path)
    usage_path = workspace / "usage.json"
    browser_bin = registry.runtime_root / "browser-venv" / "bin"
    daemon_name = _browser_daemon_name(worker.id, str(context["application_id"]), attempt_id)
    command = [
        hermes_cli(), "-p", worker.hermes_profile,
        "--model", WORKER_MODEL, "--provider", WORKER_PROVIDER,
        "--reasoning", WORKER_REASONING,
        "--skills", "chiron-application-executor", "--usage-file", str(usage_path),
        "--oneshot", RUN_PROMPT.replace("$BH_AGENT_WORKSPACE", str(workspace)),
    ]
    environment = {
        **os.environ,
        "HERMES_HOME": str(worker.hermes_home),
        "PATH": f"{browser_bin}:{os.environ.get('PATH', '')}",
        "CHIRONJP_BROWSER_HARNESS": str(browser_bin / "browser-harness"),
        "CHIRONJP_BROWSER_USE": str(browser_bin / "browser-use"),
        "BU_NAME": daemon_name,
        "BROWSER_CDP_URL": worker.cdp_url,
        "BU_CDP_URL": worker.cdp_url,
        "BH_AGENT_WORKSPACE": str(workspace),
        "BH_RUNTIME_DIR": str(registry.runtime_root / "browser-use-runtime" / worker.id),
        "BH_RUNTIME_DIR_SHARED": "1",
        "BH_TMP_DIR": str(workspace),
        "CHIRON_APPLICATION_ID": str(context["application_id"]),
        "CHIRON_ATTEMPT_ID": attempt_id,
        "PYTHONPATH": f"{REPO_ROOT}:{os.environ.get('PYTHONPATH', '')}",
    }
    log_path = workspace / "worker.log"
    with log_path.open("ab", buffering=0) as log:
        private_file(log_path)
        try:
            result = subprocess.run(
                command, cwd=workspace, env=environment, stdout=log,
                stderr=subprocess.STDOUT, timeout=timeout_seconds, check=False,
            )
            return_code = int(result.returncode)
        except subprocess.TimeoutExpired:
            return_code = 124
        except Exception as exc:
            store.fail_attempt(
                attempt_id, code="worker_launch_failed",
                detail=f"{type(exc).__name__}: {exc}",
            )
            raise
    try:
        review = store.retained_review(attempt_id)
    except ValueError:
        review = None
    if review is None:
        code = "worker_timeout" if return_code == 124 else "worker_unfulfilled"
        failure = store.fail_attempt(
            attempt_id, code=code,
            detail=f"Hermes exited with code {return_code} without a retained Review",
        )
    else:
        failure = None
    return {
        "state": "review" if review else "failed",
        "return_code": return_code,
        "attempt_id": attempt_id,
        "workspace": str(workspace),
        "review": review,
        "failure": failure,
    }


def _operator_process_running(workspace: Path) -> bool:
    """Detect an orphaned exact-workspace Hermes child before recovery."""
    marker = str(workspace).encode()
    for process in Path("/proc").glob("[0-9]*"):
        try:
            arguments = (process / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if marker in arguments and any(b"hermes" in argument.lower() for argument in arguments):
            return True
    return False


def claim_and_run(
    store: Store, registry: Registry, *, package_id: str, worker_id: str,
    timeout_seconds: int = 2100,
) -> Mapping[str, Any]:
    worker = registry.worker(worker_id)
    private_dir(worker.workspace)
    lock_path = worker.workspace / "browser-execution.lock"
    with lock_path.open("a+b") as lock:
        private_file(lock_path)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # The held lock is the process-liveness proof. Never launch a
            # second operator merely because a durable claim is idempotent.
            active = store.running_attempt(worker_id)
            attempt_id = str(active["id"]) if active and active["package_id"] == package_id else None
            return {"state": "active", "attempt_id": attempt_id, "worker_id": worker_id}
        try:
            attempt = store.claim_package(package_id, worker_id)
            workspace = _workspace(worker, str(attempt["id"]))
            if _operator_process_running(workspace):
                return {
                    "state": "active", "attempt_id": str(attempt["id"]),
                    "worker_id": worker_id,
                }
            return run_attempt(
                store, registry, str(attempt["id"]), timeout_seconds=timeout_seconds,
            )
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
