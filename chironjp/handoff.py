"""Owner-only control handoff for one retained application target.

This module is the controller side of the browser boundary.  It is deliberately
not exposed through the browser-worker helpers or a command-line entry point.
An authenticated Review transport records the connected session before calling
``take_control``.  Browser workers keep the final-action guard installed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Mapping
from urllib.request import urlopen

from .browser_tools import _FINAL_GUARD_JS
from .paths import private_dir, private_file, require_within


_LOCK = threading.RLock()
_WORKER_LOCKS: dict[str, threading.RLock] = {}
_CONNECTED: dict[str, str] = {}


def _worker_lock(worker: Any) -> threading.RLock:
    with _LOCK:
        return _WORKER_LOCKS.setdefault(str(worker.id), threading.RLock())


def binding(tab: Mapping[str, Any]) -> str:
    """Return the stable, non-secret identity of one retained application tab."""
    values = [tab[key] for key in (
        "application_id", "worker_id", "profile_name", "target_id", "opened_at",
    )]
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()[:24]


def register_connected_owner(tab: Mapping[str, Any], session: str) -> str:
    """Bind an already-authenticated Review transport to its exact retained tab.

    Authentication and same-origin checks belong in the Review HTTP/WebSocket
    edge.  That edge should call this only after both have succeeded.
    """
    if not session or len(session) > 256:
        raise ValueError("owner session identifier is required")
    bound = binding(tab)
    with _LOCK:
        prior = _CONNECTED.get(session)
        if prior is not None and prior != bound:
            raise ValueError("owner session is already bound to another retained target")
        _CONNECTED[session] = bound
    return bound


def unregister_connected_owner(session: str) -> None:
    with _LOCK:
        _CONNECTED.pop(session, None)


def _control_path(worker: Any) -> Path:
    return Path(worker.workspace) / "takeover" / "human-control.json"


def _require_worker_binding(tab: Mapping[str, Any], worker: Any) -> None:
    if str(tab.get("worker_id")) != str(worker.id):
        raise ValueError("retained target is not assigned to this worker")


def _save_control(path: Path, record: Mapping[str, Any]) -> None:
    private_dir(path.parent)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    private_file(temporary)
    os.replace(temporary, path)
    private_file(path)


def _process_identity(pid: int) -> str | None:
    try:
        # Linux starttime prevents a recycled PID from inheriting ownership.
        return (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def _application_processes(registry: Any, worker: Any, tab: Mapping[str, Any]) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    runtime = str(Path(registry.runtime_root) / "browser-use-runtime" / str(worker.id))
    app_id = str(tab["application_id"]).encode()
    excluded = (b"chromium", b"Xvfb", b"x11vnc", b"websockify")
    for process in Path("/proc").iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            environment = dict(
                value.split(b"=", 1)
                for value in (process / "environ").read_bytes().split(b"\0")
                if b"=" in value
            )
            command = (process / "cmdline").read_bytes()
            exact_application = environment.get(b"CHIRON_APPLICATION_ID") == app_id
            owned_daemon = environment.get(b"BH_RUNTIME_DIR") == runtime.encode() and b"chromium" not in command
            if (exact_application or owned_daemon) and not any(name in command for name in excluded):
                identity = _process_identity(int(process.name))
                if identity:
                    matches.append((int(process.name), identity))
        except (OSError, ValueError):
            continue
    return matches


def _target(worker: Any, target_id: str) -> Mapping[str, Any]:
    targets = json.load(urlopen(str(worker.cdp_url) + "/json/list", timeout=3))
    target = next(
        (item for item in targets if item.get("id") == target_id and item.get("type") == "page"),
        None,
    )
    if target is None:
        raise RuntimeError("retained application target is missing")
    return target


def _activate_target(worker: Any, target_id: str) -> None:
    _target(worker, target_id)
    urlopen(str(worker.cdp_url) + "/json/activate/" + target_id, timeout=3).read()
    _target(worker, target_id)


def _browser_control_cdp(url: str, target_id: str, action: str, capture_path: str = "") -> dict[str, Any]:
    """Take, observe, or return one page and its directly owned frame targets."""
    if action not in {"take", "observe", "return"}:
        raise ValueError("unknown browser handoff action")
    try:
        from websockets.sync.client import connect
    except ImportError as exc:  # pragma: no cover - environment-dependent failure message
        raise RuntimeError("browser handoff requires the Python 'websockets' package") from exc

    targets = json.load(urlopen(url + "/json/list", timeout=3))
    target = next(
        (item for item in targets if item.get("id") == target_id and item.get("type") == "page"),
        None,
    )
    if target is None:
        raise RuntimeError("retained application target is missing")

    with connect(target["webSocketDebuggerUrl"], max_size=24 * 1024 * 1024) as websocket:
        sequence = 0

        def cdp(method: str, session: str | None = None, **params: Any) -> dict[str, Any]:
            nonlocal sequence
            sequence += 1
            command: dict[str, Any] = {"id": sequence, "method": method, "params": params}
            if session:
                command["sessionId"] = session
            websocket.send(json.dumps(command))
            while True:
                reply = json.loads(websocket.recv(timeout=8))
                if reply.get("id") != sequence:
                    continue
                if "error" in reply:
                    raise RuntimeError("application frame unavailable")
                return reply["result"]

        sessions: list[str | None] = [None]
        seen: set[str] = set()
        frames = [
            item for item in cdp("Target.getTargets")["targetInfos"]
            if item.get("type") == "iframe"
        ]
        # `sessions` grows while iterating so nested, directly-owned frame
        # targets remain in the same handoff boundary.
        for parent in sessions:
            for frame in frames:
                frame_id = frame["targetId"]
                if frame_id in seen:
                    continue
                try:
                    cdp("DOM.getFrameOwner", parent, frameId=frame_id)
                except RuntimeError:
                    continue
                attached = cdp("Target.attachToTarget", targetId=frame_id, flatten=True)
                sessions.append(attached["sessionId"])
                seen.add(frame_id)

        if action == "return":
            time.sleep(1.25)
        elif action == "observe":
            time.sleep(0.1)

        expression = r'''(() => {
          const mode=MODE;
          const handoff = win => {
            const doc=win.document;
            if (mode==='take') {
              const guard=win.__chironFinalGuardState;
              if (guard?.version===5 && win.__chironFinalGuardInstalled
                  && typeof getEventListeners === 'function') {
                let removed=0;
                for (const kind of ['click','submit']) for (const item of (getEventListeners(doc)[kind] || [])) {
                  if (String(item.listener).includes('__chironBlockedFinalAction')) {
                    doc.removeEventListener(kind,item.listener,item.useCapture);removed+=1;
                  }
                }
                if(removed>=2 && typeof guard.nativeSubmit==='function') {
                  win.HTMLFormElement.prototype.submit=guard.nativeSubmit;
                  win.__chironFinalGuardInstalled=false;
                }
              } else if (!guard && typeof getEventListeners === 'function') {
                for (const kind of ['click','submit']) for (const item of (getEventListeners(doc)[kind] || [])) {
                  if (String(item.listener).includes('__chironBlockedFinalAction'))
                    doc.removeEventListener(kind,item.listener,item.useCapture);
                }
                win.__chironFinalGuardInstalled=false;
              }
              if (!win.__chironHumanHandoff) {
                const h=win.__chironHumanHandoff={clicks:[],edits:0,pending:null,lastFinal:null};
                try{win.sessionStorage.setItem('__chironHumanHandoffEvidence',JSON.stringify({clicks:[],edits:0}))}catch(e){}
                h.persist=()=>{try{win.sessionStorage.setItem('__chironHumanHandoffEvidence',JSON.stringify({clicks:h.clicks,edits:h.edits}))}catch(e){}};
                h.click=e=>{const c=e.target?.closest?.('button,input[type=submit],[role=button],a');
                  const label=String(c?.innerText||c?.value||c?.getAttribute('aria-label')||'').trim();
                  const final=/^(submit|submit application|send|confirm)$/i.test(label)||(c?.id==='fbqa_apply'&&/^apply$/i.test(label));
                  if(e.isTrusted && final) {
                    const now=Date.now(),same=h.lastFinal?.control===c && now-h.lastFinal.at<750;
                    if(same){e.preventDefault();e.stopImmediatePropagation();h.clicks.push({label,at:new Date().toISOString(),deduped:true});h.persist();return;}
                    h.lastFinal={control:c,at:now};h.clicks.push({label,at:new Date().toISOString(),deduped:false});h.persist();
                    if(c.form)h.pending={form:c.form,consumed:false};
                  }};
                h.input=e=>{if(e.isTrusted){h.edits+=1;h.persist();}};
                h.submit=()=>{if(h.pending)h.pending.consumed=true;};
                doc.addEventListener('click',h.click,true);doc.addEventListener('input',h.input,true);doc.addEventListener('submit',h.submit,true);
              }
              if(guard) {if([2,3,4].includes(guard.version)) guard.active=false;delete guard.continuation;}
              if(guard?.version!==5) win.__chironFinalGuardInstalled=false;
              const initialText=String(doc.body?.innerText||'').replace(/\s+/g,' ').trim();
              const initialNegative=initialText.match(/\bnot submitted\b/i);
              const initialSuccess=initialNegative?null:initialText.match(/(?:application (?:was |has been )?(?:submitted|received)|thank you for applying|successfully submitted|we (?:have )?received your application)/i);
              results.push({initial:{url:location.href,success:initialSuccess?.[0]||'',notSubmitted:initialNegative?.[0]||''},
                guardInstalled:win.__chironFinalGuardInstalled===true,guardActive:win.__chironFinalGuardState?.active===true,humanHandoff:!!win.__chironHumanHandoff});
            } else {
              const h=win.__chironHumanHandoff;let persisted={clicks:[],edits:0};
              try{persisted=JSON.parse(win.sessionStorage.getItem('__chironHumanHandoffEvidence')||'{}')}catch(e){}
              if(mode==='return') {
                const pending=h?.pending;win.eval(GUARD);
                if(pending && !pending.consumed && win.__chironFinalGuardState?.active)
                  win.__chironFinalGuardState.continuation=pending;
                try{win.sessionStorage.removeItem('__chironHumanHandoffEvidence')}catch(e){}
              }
              if(h && mode==='return') {
                doc.removeEventListener('click',h.click,true);doc.removeEventListener('input',h.input,true);doc.removeEventListener('submit',h.submit,true);delete win.__chironHumanHandoff;
              }
              const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
              const norm=s=>String(s||'').replace(/\s+/g,' ').trim();
              const text=norm(doc.body?.innerText).slice(0,24000);
              const invalid=[...doc.querySelectorAll(':invalid')].filter(visible).slice(0,20).map(e=>norm(e.labels?.[0]?.innerText||e.getAttribute('aria-label')||e.name||e.id||e.tagName));
              const errors=[...doc.querySelectorAll('[role=alert],[aria-live=assertive],[class*=error i],[data-automation-id*=error i]')].filter(visible).map(e=>norm(e.innerText)).filter(Boolean).slice(0,20);
              const notSubmitted=text.match(/\bnot submitted\b/i);
              const success=notSubmitted?null:text.match(/(?:application (?:was |has been )?(?:submitted|received)|thank you for applying|successfully submitted|we (?:have )?received your application)/i);
              const captcha=!!doc.querySelector('iframe[src*="recaptcha" i],iframe[src*="hcaptcha" i],.g-recaptcha,.h-captcha,[data-sitekey]');
              const auth=/(?:verification code|one[- ]time code|sign in to continue|log in to continue)/i.test(text);
              results.push({clicks:h?.clicks||persisted.clicks||[],edits:h?.edits||persisted.edits||0,
                snapshot:{url:location.href,invalid,errors,captcha,auth,success:success?.[0]||'',notSubmitted:notSubmitted?.[0]||''},
                guardInstalled:win.__chironFinalGuardInstalled===true,guardActive:win.__chironFinalGuardState?.active===true,humanHandoff:!!win.__chironHumanHandoff});
            }
            for(const f of doc.querySelectorAll('iframe'))try{handoff(f.contentWindow)}catch(e){}
          };
          const results=[];handoff(window);return {human:mode==='take',clicks:results};
        })()'''.replace("MODE", json.dumps(action)).replace("GUARD", json.dumps(_FINAL_GUARD_JS))

        results: list[dict[str, Any]] = []
        for session in sessions:
            reply = cdp(
                "Runtime.evaluate", session, expression=expression,
                returnByValue=True, includeCommandLineAPI=True,
            )
            if reply.get("exceptionDetails"):
                raise RuntimeError("application guard handoff failed")
            results.append(reply["result"].get("value") or {})

        capture: dict[str, str] = {}
        if action != "take" and capture_path:
            cdp("Runtime.evaluate", expression="""(() => {globalThis.__chironHumanMasked=[...document.querySelectorAll('input[autocomplete=one-time-code],input[id^=security-input-]')].map(e=>[e,e.style.getPropertyValue('-webkit-text-security'),e.style.getPropertyPriority('-webkit-text-security')]);for(const [e] of globalThis.__chironHumanMasked)e.style.setProperty('-webkit-text-security','disc','important');return true})()""")
            try:
                image = base64.b64decode(cdp(
                    "Page.captureScreenshot", format="png", captureBeyondViewport=False,
                )["data"])
                path = Path(capture_path)
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with path.open("xb") as handle:
                    os.chmod(path, 0o600)
                    handle.write(image)
                    handle.flush()
                    os.fsync(handle.fileno())
                capture = {"path": str(path), "sha256": hashlib.sha256(image).hexdigest()}
            finally:
                cdp("Runtime.evaluate", expression="""(() => {for(const [e,value,priority] of (globalThis.__chironHumanMasked||[])){if(value)e.style.setProperty('-webkit-text-security',value,priority);else e.style.removeProperty('-webkit-text-security')}delete globalThis.__chironHumanMasked;return true})()""")
        return {"frames": len(sessions), "results": results, "screenshot": capture}


def _guard_absent(result: Mapping[str, Any]) -> bool:
    outer = result.get("results", [])
    if not isinstance(outer, list) or not outer:
        return False
    for payload in outer:
        records = payload.get("clicks", []) if isinstance(payload, Mapping) else []
        if not isinstance(records, list) or not records or not all(
            isinstance(record, Mapping)
            and record.get("guardInstalled") is False
            and record.get("guardActive") is True
            and record.get("humanHandoff") is True
            for record in records
        ):
            return False
    return True


def _guard_armed(result: Mapping[str, Any]) -> bool:
    outer = result.get("results", [])
    if not isinstance(outer, list) or not outer:
        return False
    for payload in outer:
        records = payload.get("clicks", []) if isinstance(payload, Mapping) else []
        if not isinstance(records, list) or not records or not all(
            isinstance(record, Mapping)
            and record.get("guardInstalled") is True
            and record.get("guardActive") is True
            and record.get("humanHandoff") is False
            for record in records
        ):
            return False
    return True


def _owned_vnc_pid(worker: Any) -> int:
    path = _control_path(worker).parent / "x11vnc.pid"
    try:
        pid = int(path.read_text(encoding="ascii").strip())
        command = [
            value.decode(errors="replace")
            for value in (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
            if value
        ]
    except (OSError, ValueError) as exc:
        raise RuntimeError("worker-owned x11vnc process is unavailable") from exc
    required_pairs = (("-display", str(worker.x_display)), ("-rfbport", str(worker.vnc_port)))
    if not command or "x11vnc" not in Path(command[0]).name or not all(
        option in command and command.index(option) + 1 < len(command)
        and command[command.index(option) + 1] == value
        for option, value in required_pairs
    ):
        raise RuntimeError("x11vnc PID does not belong to this worker")
    return pid


def _set_vnc_view_only(worker: Any, value: bool) -> None:
    _owned_vnc_pid(worker)
    subprocess.run(
        ["x11vnc", "-display", str(worker.x_display), "-R", "viewonly" if value else "noviewonly"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=True, timeout=5,
    )


def _verify_stopped(processes: list[list[Any]]) -> None:
    for pid, started in processes:
        if _process_identity(int(pid)) != started:
            continue
        state = Path(f"/proc/{pid}/status").read_text().split("State:", 1)[1].splitlines()[0]
        if "T" not in state:
            raise RuntimeError("worker has not yielded browser input")


def _resume_processes(saved: Mapping[str, Any]) -> None:
    # Browser-use execution is discarded because its cached coordinates are
    # stale after a human edit. Other exact-application producers may resume.
    for pid, started in saved.get("processes", []):
        pid = int(pid)
        if _process_identity(pid) != started:
            continue
        try:
            arguments = b" ".join(Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")[1:])
            os.kill(pid, signal.SIGKILL if b"browser-use" in arguments or b"browser_use" in arguments else signal.SIGCONT)
        except (OSError, ProcessLookupError):
            continue


def _capture_path(worker: Any, session: str) -> Path:
    token = hashlib.sha256(session.encode()).hexdigest()[:24]
    root = require_within(
        Path(worker.workspace) / "takeover" / "evidence" / token,
        Path(worker.workspace), "handoff capture directory",
    )
    private_dir(root)
    return root / f"after-{time.time_ns()}.png"


def take_control(registry: Any, tab: Mapping[str, Any], worker: Any, *, session: str) -> dict[str, Any]:
    """Pause producers and enable human input only after exact guard removal."""
    _require_worker_binding(tab, worker)
    bound = binding(tab)
    with _worker_lock(worker):
        with _LOCK:
            if _CONNECTED.get(session) != bound:
                raise ValueError("connect this exact authenticated desktop before taking control")
        path = _control_path(worker)
        saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if saved:
            if saved.get("binding") != bound or saved.get("session") != session:
                raise ValueError("another desktop session has control")
            _activate_target(worker, str(tab["target_id"]))
            observed = _browser_control_cdp(worker.cdp_url, str(tab["target_id"]), "observe")
            if not _guard_absent(observed):
                raise RuntimeError("human guard-removal state was not retained; input remains disabled")
            _set_vnc_view_only(worker, False)
            return {"resumed": True, "binding": bound}

        private_dir(path.parent)
        saved = {
            "binding": bound, "application_id": str(tab["application_id"]),
            "target_id": str(tab["target_id"]), "session": session,
            "processes": [], "started_at": time.time(),
        }
        _save_control(path, saved)
        guard_removed = False
        try:
            # Two passes close the narrow window in which the application worker
            # can spawn its browser-input daemon while the marker is appearing.
            for _ in range(2):
                for pid, started in _application_processes(registry, worker, tab):
                    if [pid, started] not in saved["processes"]:
                        saved["processes"].append([pid, started])
                        _save_control(path, saved)
                        os.kill(pid, signal.SIGSTOP)
            _verify_stopped(saved["processes"])
            _activate_target(worker, str(tab["target_id"]))
            taken = _browser_control_cdp(worker.cdp_url, str(tab["target_id"]), "take")
            guard_removed = True
            if not _guard_absent(taken):
                raise RuntimeError("final-action guard removal could not be verified; input remains disabled")
            saved["browser_take"] = taken
            _save_control(path, saved)
            _set_vnc_view_only(worker, False)
            return {"resumed": False, "binding": bound, "browser": taken}
        except Exception:
            try:
                _set_vnc_view_only(worker, True)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                pass
            if guard_removed:
                try:
                    returned = _browser_control_cdp(worker.cdp_url, str(tab["target_id"]), "return")
                    if _guard_armed(returned):
                        _resume_processes(saved)
                        path.unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                _resume_processes(saved)
                path.unlink(missing_ok=True)
            raise


def observe_control(tab: Mapping[str, Any], worker: Any, *, session: str) -> dict[str, Any]:
    """Observe the exact retained target while its authenticated lease is active."""
    _require_worker_binding(tab, worker)
    with _worker_lock(worker):
        path = _control_path(worker)
        saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if not saved or saved.get("session") != session or saved.get("binding") != binding(tab):
            return {"state": "view_only"}
        result = _browser_control_cdp(worker.cdp_url, str(tab["target_id"]), "observe")
        if not _guard_absent(result):
            raise RuntimeError("retained target no longer has a verified human handoff")
        return {"state": "human_control", "browser": result}


def return_control(registry: Any, tab: Mapping[str, Any], worker: Any, *, session: str) -> dict[str, Any] | None:
    """Disable input, re-arm/verify the guard, then resume owned producers."""
    del registry  # retained for a symmetric controller API and future store integration
    _require_worker_binding(tab, worker)
    with _worker_lock(worker):
        path = _control_path(worker)
        saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if not saved:
            return None
        if saved.get("session") != session or saved.get("binding") != binding(tab):
            raise ValueError("this owner session does not own the retained target")
        input_error: Exception | None = None
        try:
            _set_vnc_view_only(worker, True)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            # Re-arm the browser guard even when the VNC control command fails.
            # The producer remains paused and the ownership marker remains until
            # both protections have been verified.
            input_error = exc
        capture = _capture_path(worker, session)
        returned = _browser_control_cdp(
            worker.cdp_url, str(tab["target_id"]), "return", str(capture),
        )
        if not _guard_armed(returned):
            raise RuntimeError("final-action guard was not re-armed; worker remains paused")
        if input_error is not None:
            raise RuntimeError("VNC input could not be disabled; guard is armed and worker remains paused") from input_error
        audit_path = path.parent / "last-handoff.json"
        _save_control(audit_path, {**saved, "returned_at": time.time(), "browser": returned})
        path.unlink(missing_ok=True)
        _resume_processes(saved)
        return {"state": "returned", "browser": returned}
