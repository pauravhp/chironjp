import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen
from unittest.mock import patch

from chironjp import handoff
from chironjp.browser_tools import _FINAL_GUARD_JS


def _browser_result(*, armed: bool, human: bool) -> dict:
    return {
        "frames": 1,
        "results": [{"human": human, "clicks": [{
            "guardInstalled": armed,
            "guardActive": True,
            "humanHandoff": human,
        }]}],
        "screenshot": {},
    }


class HandoffControllerTests(unittest.TestCase):
    def setUp(self):
        handoff._CONNECTED.clear()
        handoff._WORKER_LOCKS.clear()
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.worker = SimpleNamespace(
            id="worker-one", workspace=root / "worker-one", x_display=":151",
            vnc_port=19551, cdp_url="http://127.0.0.1:19251",
        )
        self.registry = SimpleNamespace(runtime_root=root / "runtime")
        self.tab = {
            "application_id": "application-one", "worker_id": "worker-one",
            "profile_name": "profile-one", "target_id": "target-one",
            "opened_at": "2026-01-01T00:00:00Z",
        }
        handoff.register_connected_owner(self.tab, "session-one")

    def tearDown(self):
        self.temporary.cleanup()
        handoff._CONNECTED.clear()
        handoff._WORKER_LOCKS.clear()

    def test_session_is_bound_to_exact_retained_target(self):
        changed = {**self.tab, "target_id": "target-two"}
        with self.assertRaisesRegex(ValueError, "another retained target"):
            handoff.register_connected_owner(changed, "session-one")
        with self.assertRaisesRegex(ValueError, "exact authenticated desktop"):
            handoff.take_control(self.registry, self.tab, self.worker, session="not-connected")
        wrong_worker = SimpleNamespace(**{**self.worker.__dict__, "id": "worker-two"})
        with self.assertRaisesRegex(ValueError, "not assigned"):
            handoff.take_control(
                self.registry, self.tab, wrong_worker, session="session-one",
            )

    def test_take_pauses_producer_and_verifies_guard_before_enabling_input(self):
        order = []

        def stop(pid, signal_number):
            order.append(("signal", pid, signal_number))

        with patch.object(handoff, "_application_processes", side_effect=[[(4123, "77")], [(4123, "77")]]), \
             patch.object(handoff, "_process_identity", return_value="77"), \
             patch.object(handoff, "_verify_stopped", side_effect=lambda _: order.append(("stopped",))), \
             patch.object(handoff, "_activate_target", side_effect=lambda *_: order.append(("activate",))), \
             patch.object(handoff, "_browser_control_cdp", side_effect=lambda *_: order.append(("browser-take",)) or _browser_result(armed=False, human=True)), \
             patch.object(handoff, "_set_vnc_view_only", side_effect=lambda _, value: order.append(("vnc", value))), \
             patch.object(handoff.os, "kill", side_effect=stop):
            result = handoff.take_control(
                self.registry, self.tab, self.worker, session="session-one",
            )

        self.assertFalse(result["resumed"])
        self.assertLess(order.index(("stopped",)), order.index(("activate",)))
        self.assertLess(order.index(("activate",)), order.index(("browser-take",)))
        self.assertLess(order.index(("browser-take",)), order.index(("vnc", False)))
        self.assertIn(("signal", 4123, handoff.signal.SIGSTOP), order)
        saved = json.loads(handoff._control_path(self.worker).read_text())
        self.assertEqual(saved["target_id"], "target-one")
        self.assertEqual(saved["processes"], [[4123, "77"]])

    def test_take_never_enables_input_when_guard_removal_is_unverified(self):
        vnc = []
        browser = [
            _browser_result(armed=True, human=True),
            _browser_result(armed=True, human=False),
        ]
        with patch.object(handoff, "_application_processes", return_value=[]), \
             patch.object(handoff, "_activate_target"), \
             patch.object(handoff, "_browser_control_cdp", side_effect=browser), \
             patch.object(handoff, "_set_vnc_view_only", side_effect=lambda _, value: vnc.append(value)), \
             patch.object(handoff, "_resume_processes"):
            with self.assertRaisesRegex(RuntimeError, "removal could not be verified"):
                handoff.take_control(
                    self.registry, self.tab, self.worker, session="session-one",
                )
        self.assertNotIn(False, vnc)

    def test_return_disables_input_and_rearms_guard_before_resuming(self):
        order = []
        handoff._save_control(handoff._control_path(self.worker), {
            "binding": handoff.binding(self.tab), "application_id": "application-one",
            "target_id": "target-one", "session": "session-one", "processes": [],
        })
        with patch.object(handoff, "_set_vnc_view_only", side_effect=lambda _, value: order.append(("vnc", value))), \
             patch.object(handoff, "_browser_control_cdp", side_effect=lambda *_: order.append(("browser-return",)) or _browser_result(armed=True, human=False)), \
             patch.object(handoff, "_resume_processes", side_effect=lambda *_: order.append(("resume",))):
            result = handoff.return_control(
                self.registry, self.tab, self.worker, session="session-one",
            )
        self.assertEqual(result["state"], "returned")
        self.assertEqual(order, [("vnc", True), ("browser-return",), ("resume",)])
        self.assertFalse(handoff._control_path(self.worker).exists())
        self.assertTrue((handoff._control_path(self.worker).parent / "last-handoff.json").exists())

    def test_return_fails_closed_and_keeps_marker_when_rearm_is_unverified(self):
        path = handoff._control_path(self.worker)
        handoff._save_control(path, {
            "binding": handoff.binding(self.tab), "application_id": "application-one",
            "target_id": "target-one", "session": "session-one", "processes": [],
        })
        with patch.object(handoff, "_set_vnc_view_only") as view_only, \
             patch.object(handoff, "_browser_control_cdp", return_value=_browser_result(armed=False, human=True)), \
             patch.object(handoff, "_resume_processes") as resume:
            with self.assertRaisesRegex(RuntimeError, "not re-armed"):
                handoff.return_control(
                    self.registry, self.tab, self.worker, session="session-one",
                )
        view_only.assert_called_once_with(self.worker, True)
        resume.assert_not_called()
        self.assertTrue(path.exists())

    def test_return_rearms_guard_even_when_vnc_disable_fails(self):
        path = handoff._control_path(self.worker)
        handoff._save_control(path, {
            "binding": handoff.binding(self.tab), "application_id": "application-one",
            "target_id": "target-one", "session": "session-one", "processes": [],
        })
        with patch.object(handoff, "_set_vnc_view_only", side_effect=RuntimeError("control failed")), \
             patch.object(handoff, "_browser_control_cdp", return_value=_browser_result(armed=True, human=False)) as browser, \
             patch.object(handoff, "_resume_processes") as resume:
            with self.assertRaisesRegex(RuntimeError, "VNC input could not be disabled"):
                handoff.return_control(
                    self.registry, self.tab, self.worker, session="session-one",
                )
        browser.assert_called_once()
        resume.assert_not_called()
        self.assertTrue(path.exists())

    def test_every_attached_session_must_prove_the_same_guard_state(self):
        incomplete = _browser_result(armed=False, human=True)
        incomplete["results"].append({"human": True, "clicks": []})
        self.assertFalse(handoff._guard_absent(incomplete))
        self.assertFalse(handoff._guard_armed(incomplete))

    def test_observe_rejects_guard_or_target_drift(self):
        path = handoff._control_path(self.worker)
        handoff._save_control(path, {
            "binding": handoff.binding(self.tab), "session": "session-one", "processes": [],
        })
        with patch.object(handoff, "_browser_control_cdp", return_value=_browser_result(armed=True, human=False)):
            with self.assertRaisesRegex(RuntimeError, "no longer has"):
                handoff.observe_control(self.tab, self.worker, session="session-one")
        changed = {**self.tab, "target_id": "other"}
        self.assertEqual(
            handoff.observe_control(changed, self.worker, session="session-one"),
            {"state": "view_only"},
        )


@unittest.skipUnless(os.environ.get("CHIRONJP_BROWSER_INTEGRATION") == "1", "opt-in real Chromium proof")
class ChromiumHandoffIntegrationTests(unittest.TestCase):
    def test_real_chromium_guard_take_and_return(self):
        try:
            from websockets.sync.client import connect
        except ImportError as exc:
            self.skipTest(str(exc))
        chromium = shutil.which("chromium") or shutil.which("chromium-browser")
        if not chromium:
            self.skipTest("Chromium unavailable")
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            port = candidate.getsockname()[1]
        with tempfile.TemporaryDirectory() as temporary:
            process = subprocess.Popen([
                chromium, "--headless=new", "--no-sandbox", "--disable-gpu",
                "--disable-dev-shm-usage", "--no-first-run",
                f"--user-data-dir={temporary}", f"--remote-debugging-port={port}",
                "--remote-debugging-address=127.0.0.1", "about:blank",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            try:
                endpoint = f"http://127.0.0.1:{port}"
                for _ in range(100):
                    try:
                        targets = json.load(urlopen(endpoint + "/json/list", timeout=0.2))
                        break
                    except OSError:
                        if process.poll() is not None:
                            self.fail("Chromium exited before exposing CDP")
                        time.sleep(0.05)
                else:
                    self.fail("Chromium did not expose CDP")
                target = next(item for item in targets if item["type"] == "page")
                with connect(target["webSocketDebuggerUrl"]) as websocket:
                    sequence = 0

                    def js(expression):
                        nonlocal sequence
                        sequence += 1
                        websocket.send(json.dumps({
                            "id": sequence, "method": "Runtime.evaluate",
                            "params": {"expression": expression, "returnByValue": True},
                        }))
                        while True:
                            reply = json.loads(websocket.recv(timeout=5))
                            if reply.get("id") == sequence:
                                return reply["result"]["result"].get("value")

                    js("document.body.innerHTML='<form><button type=submit>Submit application</button></form>';window.submits=0;document.querySelector('form').onsubmit=e=>{e.preventDefault();window.submits++}")
                    self.assertTrue(js(_FINAL_GUARD_JS))
                    js("document.querySelector('button').click()")
                    self.assertEqual(js("window.submits"), 0)

                    taken = handoff._browser_control_cdp(endpoint, target["id"], "take")
                    self.assertTrue(handoff._guard_absent(taken))
                    js("document.querySelector('button').click()")
                    self.assertEqual(js("window.submits"), 1)

                    returned = handoff._browser_control_cdp(endpoint, target["id"], "return")
                    self.assertTrue(handoff._guard_armed(returned))
                    js("document.querySelector('button').click()")
                    self.assertEqual(js("window.submits"), 1)
            finally:
                try:
                    os.killpg(process.pid, handoff.signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, handoff.signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
