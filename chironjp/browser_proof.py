"""Disposable Chromium proof for the extracted browser mechanics.

This module is an operator/test harness. It opens only locally constructed data
pages in a fresh temporary Chromium profile and never reports fixture actions as
an employer delivery or submission.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from . import browser_tools


class _CDPConnection:
    def __init__(self, websocket_url: str):
        try:
            from websockets.sync.client import connect
        except ImportError as exc:  # pragma: no cover - depends on optional proof tooling
            raise RuntimeError("the disposable proof requires the optional 'websockets' package") from exc
        self._socket = connect(websocket_url, max_size=24 * 1024 * 1024)
        self._sequence = 0

    def close(self) -> None:
        self._socket.close()

    def call(self, method: str, session_id: str | None = None, **params: Any) -> dict[str, Any]:
        self._sequence += 1
        sequence = self._sequence
        command: dict[str, Any] = {"id": sequence, "method": method, "params": params}
        if session_id:
            command["sessionId"] = session_id
        self._socket.send(json.dumps(command))
        while True:
            response = json.loads(self._socket.recv(timeout=10))
            if response.get("id") != sequence:
                continue
            if "error" in response:
                raise RuntimeError(str(response["error"]))
            return response["result"]

    def js(self, expression: str) -> Any:
        response = self.call(
            "Runtime.evaluate", expression=expression,
            returnByValue=True, awaitPromise=True,
        )
        if "exceptionDetails" in response:
            raise RuntimeError("fixture JavaScript evaluation failed")
        return response.get("result", {}).get("value")

    def click(self, x: float, y: float) -> None:
        for event in ("mousePressed", "mouseReleased"):
            self.call(
                "Input.dispatchMouseEvent", type=event, x=x, y=y,
                button="left", clickCount=1,
            )


def _wait_for_debugger(profile: Path, process: subprocess.Popen[bytes]) -> str:
    marker = profile / "DevToolsActivePort"
    for _ in range(100):
        if marker.exists():
            return "http://127.0.0.1:" + marker.read_text(encoding="ascii").splitlines()[0]
        if process.poll() is not None:
            raise RuntimeError(f"disposable Chromium exited with code {process.returncode}")
        time.sleep(0.1)
    raise RuntimeError("disposable Chromium did not expose its debugger")


def prove_disposable_chromium() -> dict[str, Any]:
    """Exercise the safety/readback path in fresh local Chromium state."""
    chromium = shutil.which("chromium") or shutil.which("chromium-browser")
    if not chromium:
        raise RuntimeError("Chromium is unavailable")
    with tempfile.TemporaryDirectory(prefix="chironjp-browser-proof-") as directory:
        root = Path(directory)
        profile = root / "profile"
        artifact = root / "fixture-resume.pdf"
        artifact.write_bytes(b"fictional ChironJP browser proof resume")
        process = subprocess.Popen(
            [
                chromium, "--headless=new", "--no-sandbox", "--disable-gpu",
                "--no-first-run", "--site-per-process", "--remote-debugging-port=0",
                f"--user-data-dir={profile}", "about:blank",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        connection: _CDPConnection | None = None
        original_transport = browser_tools._ORIGINAL_CDP
        try:
            endpoint = _wait_for_debugger(profile, process)
            with urlopen(endpoint + "/json/list", timeout=3) as response:
                target = next(item for item in json.load(response) if item["type"] == "page")
            connection = _CDPConnection(target["webSocketDebuggerUrl"])
            connection.call(
                "Emulation.setDeviceMetricsOverride", width=800, height=500,
                deviceScaleFactor=1, mobile=False,
            )
            connection.js(r"""document.body.innerHTML=`
              <main><h1>Fictional application fixture</h1>
              <div data-automation-id="applicationQuestions"></div>
              <label>First name <input data-automation-id="firstName" required></label>
              <label>Country <select data-automation-id="country" required>
                <option></option><option value="CA">Canada</option></select></label>
              <label>Resume <input type="file" data-automation-id="resumeUpload" required></label>
              <button id="next" onclick="window.advanced=true">Next</button></main>`;
              window.advanced=false;""")
            observed = browser_tools.workday_observe(connection.js)

            def fill_input(selector: str, value: str) -> None:
                connection.js(
                    "document.querySelector(" + json.dumps(selector) + ").focus();"
                    "document.querySelector(" + json.dumps(selector) + ").value=''"
                )
                connection.call("Input.insertText", text=value)

            filled = browser_tools.trusted_batch_input(
                connection.js, fill_input,
                [{"ref": "aid:firstName", "kind": "text", "value": "Ada"}],
            )
            selected = browser_tools.exact_select(
                connection.js, connection.click, "aid:country", "Canada",
            )
            uploaded = browser_tools.upload_and_verify(
                connection.js, connection.call, "aid:resumeUpload", str(artifact),
            )
            advanced = browser_tools.advance(connection.js, connection.click)

            connection.js(r"""document.body.innerHTML=`
              <main data-automation-id="reviewPage"><h1>Review</h1>
              <button id="ordinary" type="button">Apply</button>
              <form><button id="final" type="submit">Submit</button></form></main>`;
              window.ordinaryClicks=0; window.finalSubmits=0;
              ordinary.onclick=()=>ordinaryClicks++;
              document.querySelector('form').onsubmit=e=>{e.preventDefault();finalSubmits++};""")
            review = browser_tools.review_readback(connection.js)
            connection.js("document.querySelector('#ordinary').click()")
            final_point = connection.js("""(() => {const r=document.querySelector('#final').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()""")
            connection.click(final_point["x"], final_point["y"])

            browser_tools._ORIGINAL_CDP = connection.call
            viewport_rejected = False
            try:
                browser_tools.cdp(
                    "Input.dispatchMouseEvent", type="mousePressed",
                    x=10, y=900, button="left", clickCount=1,
                )
            except ValueError:
                viewport_rejected = True

            result = {
                "contract": "chironjp-disposable-browser-proof-v1",
                "fixture_only": True,
                "stage": observed.get("stage"),
                "guard_active": observed.get("final_guard_active") is True,
                "trusted_fill": filled.get("filled") == ["aid:firstName"],
                "exact_select": selected.get("selected") is True,
                "upload_verified": uploaded.get("verified") is True,
                "advanced": advanced.get("advanced") is True,
                "review_stage": review.get("stage"),
                "ordinary_apply_usable": connection.js("window.ordinaryClicks") == 1,
                "final_action_blocked": connection.js("window.finalSubmits") == 0,
                "blocked_final_label": connection.js("globalThis.__chironBlockedFinalAction?.label || ''"),
                "viewport_rejected": viewport_rejected,
            }
            required = {
                "fixture_only": True, "stage": "autofillWithResume", "guard_active": True,
                "trusted_fill": True, "exact_select": True, "upload_verified": True,
                "advanced": True, "review_stage": "review", "ordinary_apply_usable": True,
                "final_action_blocked": True, "blocked_final_label": "Submit",
                "viewport_rejected": True,
            }
            failed = [key for key, expected in required.items() if result.get(key) != expected]
            if failed:
                raise RuntimeError(
                    "disposable Chromium invariants failed: " + ", ".join(failed)
                    + "; observed=" + json.dumps(result, sort_keys=True)
                )
            return result
        finally:
            browser_tools._ORIGINAL_CDP = original_transport
            if connection is not None:
                connection.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def main() -> int:
    print(json.dumps(prove_disposable_chromium(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
