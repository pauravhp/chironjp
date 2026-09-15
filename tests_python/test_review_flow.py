import base64
import hashlib
import json
import os
import shutil
import signal
import ssl
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from chironjp.registry import load_registry
from chironjp import browser_tools, handoff
from chironjp.browser_proof import _CDPConnection
from chironjp.review_server import ReviewHandler, ReviewServer, _review_tab, _token
from chironjp.runner import _CDP, finish_review
from chironjp.runtime import start_chromium, stop_chromium
from chironjp.store import Store, iso
from chironjp.takeover import stop_surface


class FakeCDP:
    def __init__(self, _url): pass
    def evaluate(self, expression):
        if "document.title" in expression:
            return {
                "url": "https://ats.example.test/apply/role",
                "title": "Engineer — Example Co",
                "heading": "Engineer",
                "body": "Example Co Engineer application",
            }
        return None
    def close(self): pass


class FakeTransport:
    def __init__(self): self.shutdowns = []
    def shutdown(self, how): self.shutdowns.append(how)


class PhoneCDPConnection(_CDPConnection):
    """CDP connection tolerant of a software-decoded noVNC frame on a busy host."""

    def call(self, method, session_id=None, **params):
        self._sequence += 1
        sequence = self._sequence
        command = {"id": sequence, "method": method, "params": params}
        if session_id:
            command["sessionId"] = session_id
        self._socket.send(json.dumps(command))
        while True:
            response = json.loads(self._socket.recv(timeout=45))
            if response.get("id") != sequence:
                continue
            if "error" in response:
                raise RuntimeError(str(response["error"]))
            return response["result"]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class FixturePage(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b"""<!doctype html><meta charset=utf-8><title>Fictional application fixture</title>
<style>body{font:20px system-ui;margin:24px}.spacer{height:1050px}input,button{font:inherit;min-height:48px}</style>
<h1 tabindex=0>Fictional application fixture</h1>
<form onsubmit="event.preventDefault();window.fixtureFinalActivations++">
<label>Transport field <input id=fixture-field></label>
<div class=spacer aria-hidden=true></div>
<label>Phone proof field <input id=phone-fixture-field autocomplete=off></label>
<button type=submit onclick="window.fixtureFinalActivations++">Submit Application</button>
</form><script>window.fixtureFinalActivations=0;window.fixtureKeys=[];
window.fixtureClicks=[];
addEventListener('keydown',event=>window.fixtureKeys.push({key:event.key,code:event.code}));
addEventListener('click',event=>window.fixtureClicks.push({tag:event.target.tagName,trusted:event.isTrusted}))</script>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


class ReviewFlowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        runtime, state = self.root / "runtime", self.root / "state"
        self.database = runtime / "chiron.sqlite3"
        self.registry_path = self.root / "workers.json"
        self.registry_path.write_text(json.dumps({
            "schema_version": 3, "runtime_root": str(runtime), "state_root": str(state),
            "database": str(self.database), "hermes_profile_root": str(self.root / "profiles"),
            "tailor": {"id": "tailor", "hermes_profile": "tailor", "workspace": str(state / "tailor"), "provider": "test", "model": "test", "reasoning": "high"},
            "workers": [
                {"id": "worker-one", "enabled": True, "hermes_profile": "browser-one", "chromium_profile": str(runtime / "browser/one"), "workspace": str(state / "worker-one"), "cdp_port": 39221, "display": 31, "vnc_port": 39521, "novnc_port": 39621},
                {"id": "worker-two", "enabled": False, "hermes_profile": "browser-two", "chromium_profile": str(runtime / "browser/two"), "workspace": str(state / "worker-two"), "cdp_port": 39222, "display": 32, "vnc_port": 39522, "novnc_port": 39622},
            ],
        }), encoding="utf-8")
        self.registry = load_registry(self.registry_path)
        self.store = Store(self.database)
        self.store.initialize()
        assets = self.root / "assets"
        assets.mkdir()
        self.profile = assets / "profile.json"
        self.profile.write_text(json.dumps({"identity": {}, "education": [], "work_experience": []}))
        files = {}
        for name in ("resume.pdf", "resume.tex", "selection.json", "validation.json", "preview.png", "bank.json", "template.tex"):
            path = assets / name
            path.write_text(f"fixture {name}")
            files[name] = path
        from chironjp.store import file_sha256
        with self.store.immediate() as connection:
            source_id = connection.execute(
                """INSERT INTO source_jobs(source_name,source_job_id,content_hash,source_url,resolver_url,official_apply_identity,company,role,location,description,scraped_at,disposition,application_id,imported_at,updated_at)
                   VALUES ('fixture','role','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','https://jobs.example.test/role','https://ats.example.test/apply/role','ats:role','Example Co','Engineer','Remote','Build software','2026-01-01T00:00:00+00:00','assigned','app-one',?,?)""",
                (iso(), iso()),
            ).lastrowid
            connection.execute("INSERT INTO applications(id,source_row_id,start_url,tenant_host,ats_family,status,claimable,mission_worker_id,created_at) VALUES (?,?,?,?,?,'running',0,'worker-one',?)", ("app-one", source_id, "https://ats.example.test/apply/role", "ats.example.test", "greenhouse", iso()))
            connection.execute("""INSERT INTO tailor_requests(id,request_key,source_row_id,role,description,profile_path,profile_sha256,bank_path,bank_sha256,template_path,template_sha256,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", ("req-one", "b" * 64, source_id, "Engineer", "Build software", str(self.profile), file_sha256(self.profile), str(files["bank.json"]), file_sha256(files["bank.json"]), str(files["template.tex"]), file_sha256(files["template.tex"]), iso()))
            connection.execute("""INSERT INTO tailored_artifacts(id,request_id,generation_key,resume_path,resume_sha256,source_path,source_sha256,selection_path,selection_sha256,validation_path,validation_sha256,preview_path,preview_sha256,visual_inspection_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", ("art-one", "req-one", "c" * 64, str(files["resume.pdf"]), file_sha256(files["resume.pdf"]), str(files["resume.tex"]), file_sha256(files["resume.tex"]), str(files["selection.json"]), file_sha256(files["selection.json"]), str(files["validation.json"]), file_sha256(files["validation.json"]), str(files["preview.png"]), file_sha256(files["preview.png"]), "{}", iso()))
            connection.execute("""INSERT INTO packages(id,application_id,resume_path,resume_sha256,source_path,source_sha256,manifest_path,manifest_sha256,validation_path,validation_sha256,preview_path,preview_sha256,visual_inspection_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", ("pkg-one", "app-one", str(files["resume.pdf"]), file_sha256(files["resume.pdf"]), str(files["resume.tex"]), file_sha256(files["resume.tex"]), str(files["selection.json"]), file_sha256(files["selection.json"]), str(files["validation.json"]), file_sha256(files["validation.json"]), str(files["preview.png"]), file_sha256(files["preview.png"]), "{}", iso()))
            connection.execute("INSERT INTO attempts(id,application_id,package_id,worker_id,status,started_at) VALUES ('att-one','app-one','pkg-one','worker-one','running',?)", (iso(),))
        self.store.bind_attempt_target(
            "att-one", worker_id="worker-one", target_id="target-one",
            start_url="https://ats.example.test/apply/role",
        )
        self.workspace = self.registry.worker("worker-one").workspace / "attempts/att-one"
        self.workspace.mkdir(parents=True)
        self.review_path = self.workspace / "review.json"
        self.review_path.write_text(json.dumps({
            "stage": "review", "url": "https://ats.example.test/apply/role", "target_id": "target-one",
            "observed_resume_sha256": file_sha256(files["resume.pdf"]), "rendered": {"worker": "claim"},
            "provisional": [], "final_actions": ["Submit Application"], "submit_untouched": True,
            "final_guard_active": True,
        }))

    def tearDown(self):
        handoff._CONNECTED.clear()
        self.temporary.cleanup()

    @staticmethod
    def _tab(target_id="authenticated-target"):
        return {
            "application_id": "app-one", "worker_id": "worker-one",
            "profile_name": "browser-one", "target_id": target_id,
            "opened_at": "2026-01-01T00:00:00+00:00",
        }

    def publish(self):
        target = {"id": "target-one", "type": "page", "url": "https://ats.example.test/apply/role", "webSocketDebuggerUrl": "ws://fixture"}
        observed = {"stage": "review", "url": target["url"], "final_actions": ["Submit Application"], "submit_untouched": True, "final_guard_active": True}
        with patch("chironjp.runner._target", return_value=target), patch("chironjp.runner._CDP", FakeCDP), patch("chironjp.runner.browser_tools.review_readback", return_value=observed):
            return finish_review(self.store, self.registry, attempt_id="att-one", review_path=self.review_path)

    def test_controller_readback_publishes_exact_retained_review(self):
        review = self.publish()
        self.assertEqual(review["target_id"], "target-one")
        self.assertEqual(review["profile_name"], "browser-one")
        self.assertEqual(review["rendered"]["final_guard_active"], True)
        self.assertEqual(len(self.store.list_reviews()), 1)

    def test_target_or_controller_readback_drift_is_rejected(self):
        wrong = {"id": "target-one", "type": "page", "url": "https://other.example.test/review", "webSocketDebuggerUrl": "ws://fixture"}
        with patch("chironjp.runner._target", return_value=wrong):
            with self.assertRaisesRegex(ValueError, "URL does not match"):
                finish_review(self.store, self.registry, attempt_id="att-one", review_path=self.review_path)
        observed = {"stage": "application", "url": "https://ats.example.test/apply/role", "final_actions": [], "submit_untouched": True, "final_guard_active": True}
        target = {"id": "target-one", "type": "page", "url": observed["url"], "webSocketDebuggerUrl": "ws://fixture"}
        with patch("chironjp.runner._target", return_value=target), patch("chironjp.runner._CDP", FakeCDP), patch("chironjp.runner.browser_tools.review_readback", return_value=observed):
            with self.assertRaisesRegex(ValueError, "did not prove guarded Review"):
                finish_review(self.store, self.registry, attempt_id="att-one", review_path=self.review_path)

    @unittest.skipUnless(__import__("importlib").util.find_spec("bcrypt"), "bcrypt optional dependency")
    def test_review_http_edge_denies_anonymous_then_issues_authenticated_cookie(self):
        self.publish()
        novnc = self.root / "novnc"
        (novnc / "core").mkdir(parents=True)
        (novnc / "core/rfb.js").write_text("export default class RFB {}")
        import bcrypt
        password_hash = bcrypt.hashpw(b"fixture-password", bcrypt.gensalt(rounds=4)).decode()
        with patch.dict(os.environ, {"CHIRONJP_REVIEW_USERNAME": "owner", "CHIRONJP_REVIEW_PASSWORD_HASH": password_hash}):
            server = ReviewServer(("127.0.0.1", 0), self.store, self.registry, novnc)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            root = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with self.assertRaises(HTTPError) as denied:
                    urlopen(root + "/reviews")
                self.assertEqual(denied.exception.code, 401)
                data = urlencode({"username": "owner", "password": "fixture-password"}).encode()
                request = Request(root + "/login", data=data, headers={"Origin": root}, method="POST")
                opener = build_opener(NoRedirect())
                try:
                    opener.open(request)
                except HTTPError as response:
                    self.assertEqual(response.code, 303)
                    cookie = response.headers.get("Set-Cookie")
                else:
                    self.fail("login redirect unexpectedly followed")
                self.assertIn("HttpOnly", cookie)
                cookie_value = cookie.split(";", 1)[0]
                response = urlopen(Request(root + "/reviews", headers={"Cookie": cookie_value}))
                self.assertEqual(response.status, 200)
                self.assertIn(b"Retained Reviews", response.read())
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=5)

    def _review_server(self):
        novnc = self.root / "novnc-unit"
        (novnc / "core").mkdir(parents=True, exist_ok=True)
        (novnc / "core/rfb.js").write_text("export default class RFB {}")
        return ReviewServer(("127.0.0.1", 0), self.store, self.registry, novnc)

    def test_replacement_socket_generation_owns_cleanup(self):
        server = self._review_server()
        key = ("app-one", "browser-session")
        review = {"application_id": "app-one"}
        tab = self._tab("original-target")
        worker = self.registry.worker("worker-one")
        first, second = FakeTransport(), FakeTransport()
        try:
            first_generation, replaced = server.open_connection(
                key, review=review, tab=tab, worker=worker, connection=first,
            )
            self.assertIsNone(replaced)
            second_generation, replaced = server.open_connection(
                key, review=review, tab=tab, worker=worker, connection=second,
            )
            self.assertIs(replaced, first)
            self.assertNotEqual(server.active_connection(key)["generation"], first_generation)
            self.assertEqual(server.active_connection(key)["generation"], second_generation)
            handler = object.__new__(ReviewHandler)
            handler.server = server
            handler._cleanup_proxy(key, second_generation, review, tab, worker, key[1])
            self.assertIsNone(server.active_connection(key))
        finally:
            server.server_close()

    def test_stale_socket_cannot_return_or_unregister_replacement(self):
        server = self._review_server()
        key = ("app-one", "browser-session")
        review = {"application_id": "app-one"}
        tab = self._tab()
        worker = self.registry.worker("worker-one")
        first_generation, _ = server.open_connection(
            key, review=review, tab=tab, worker=worker, connection=FakeTransport(),
        )
        second_generation, _ = server.open_connection(
            key, review=review, tab=tab, worker=worker, connection=FakeTransport(),
        )
        server.human_sessions[key] = "hrs-one"
        handler = object.__new__(ReviewHandler)
        handler.server = server
        try:
            with patch.object(handler, "_return_session") as returned, \
                 patch("chironjp.review_server.handoff.unregister_connected_owner") as unregistered:
                handler._cleanup_proxy(key, first_generation, review, tab, worker, key[1])
            returned.assert_not_called()
            unregistered.assert_not_called()
            self.assertEqual(server.active_connection(key)["generation"], second_generation)
        finally:
            server.server_close()

    def test_disconnect_cleanup_uses_original_target_and_records_failure(self):
        server = self._review_server()
        key = ("app-one", "browser-session")
        review = {"application_id": "app-one"}
        tab = self._tab()
        worker = self.registry.worker("worker-one")
        generation, _ = server.open_connection(
            key, review=review, tab=tab, worker=worker, connection=FakeTransport(),
        )
        server.human_sessions[key] = "hrs-one"
        handler = object.__new__(ReviewHandler)
        handler.server = server
        try:
            with patch.object(handler, "_return_session", side_effect=RuntimeError("guard restore not verified")) as returned, \
                 patch("chironjp.review_server.handoff.unregister_connected_owner") as unregistered:
                handler._cleanup_proxy(key, generation, review, tab, worker, key[1])
            returned.assert_called_once_with(review, tab, worker, key[1])
            unregistered.assert_called_once_with(key[1])
            self.assertEqual(server.control_failures[-1]["action"], "disconnect_return")
            self.assertIn("guard restore", server.control_failures[-1]["error"])
            self.assertIn(key, server.human_sessions)
        finally:
            server.server_close()

    def test_mobile_keyboard_and_retryable_uncertain_state_are_shipped(self):
        script = (Path(__file__).parents[1] / "chironjp/static/desktop.js").read_text()
        self.assertIn("controlState = 'uncertain'", script)
        self.assertIn("retry Return control", script)
        self.assertIn("keyboard.disabled = !connected || !controlling", script)
        self.assertIn("insertedRevision === composerRevision", script)
        self.assertIn("composerRevision += 1", script)
        self.assertIn("if (insert.disabled) return", script)
        self.assertIn("sendKeys(keyboard.value)", script)
        self.assertIn("insertedRevision = composerRevision", script)
        self.assertNotIn("event.data", script)
        self.assertNotIn("keyboard.value = ''", script)
        page_source = (Path(__file__).parents[1] / "chironjp/review_server.py").read_text()
        self.assertIn('id="insert" type="button" disabled', page_source)
        self.assertNotIn("#screen.standby canvas{{visibility:hidden}}", page_source)

    def test_cleanup_and_replacement_registration_are_one_generation_lifecycle(self):
        server = self._review_server()
        key = ("app-one", "browser-session")
        review = {"application_id": "app-one"}
        tab = self._tab()
        worker = self.registry.worker("worker-one")
        first_generation, _ = server.open_connection(
            key, review=review, tab=tab, worker=worker, connection=FakeTransport(),
        )
        server.human_sessions[key] = "hrs-one"
        handler = object.__new__(ReviewHandler)
        handler.server = server
        entered, release, replacement_opened = threading.Event(), threading.Event(), threading.Event()

        def slow_return(*_args):
            entered.set()
            self.assertTrue(release.wait(2))
            server.human_sessions.pop(key, None)
            return {"state": "returned"}

        second = {}
        def replace():
            second["generation"], _ = server.open_connection(
                key, review=review, tab=tab, worker=worker, connection=FakeTransport(),
            )
            replacement_opened.set()

        try:
            with patch.object(handler, "_return_session", side_effect=slow_return):
                cleanup = threading.Thread(
                    target=handler._cleanup_proxy,
                    args=(key, first_generation, review, tab, worker, key[1]),
                )
                cleanup.start()
                self.assertTrue(entered.wait(2))
                replacement = threading.Thread(target=replace)
                replacement.start()
                self.assertFalse(replacement_opened.wait(.1))
                release.set()
                cleanup.join(2); replacement.join(2)
            self.assertTrue(replacement_opened.is_set())
            self.assertEqual(server.active_connection(key)["generation"], second["generation"])
            self.assertEqual(handoff._CONNECTED[key[1]], handoff.binding(tab))
            handler._cleanup_proxy(key, second["generation"], review, tab, worker, key[1])
        finally:
            server.server_close()

    @unittest.skipUnless(os.environ.get("CHIRONJP_NOVNC_INTEGRATION") == "1", "real noVNC integration is opt-in")
    def test_real_authenticated_vnc_take_type_and_guarded_return(self):
        try:
            from websockets.exceptions import InvalidStatus
            from websockets.sync.client import connect
            import bcrypt
            import websockify.websocket  # noqa: F401
        except ImportError as exc:
            self.skipTest(f"optional Review transport dependency unavailable: {exc}")
        if not all(shutil.which(name) for name in ("chromium", "Xvfb", "x11vnc", "websockify")):
            self.skipTest("Chromium/Xvfb/x11vnc/websockify are required")
        if not Path("/usr/share/novnc/core/rfb.js").is_file():
            self.skipTest("noVNC web assets are required")

        page = ThreadingHTTPServer(("127.0.0.1", 0), FixturePage)
        page_thread = threading.Thread(target=page.serve_forever, daemon=True)
        page_thread.start()
        start_url = f"http://127.0.0.1:{page.server_address[1]}/application"
        worker = self.registry.worker("worker-one")
        review_server = None
        review_thread = None
        browser_started = False
        cdp = None
        websocket = None
        try:
            with self.store.immediate() as connection:
                connection.execute(
                    "UPDATE applications SET start_url=?,tenant_host='127.0.0.1' WHERE id='app-one'",
                    (start_url,),
                )
                connection.execute(
                    "UPDATE attempts SET designated_target_id=NULL,designated_start_url=NULL,designated_at=NULL,target_last_url=NULL WHERE id='att-one'",
                )
            start_chromium(self.registry, worker, initial_url=start_url)
            browser_started = True
            targets = json.load(urlopen(worker.cdp_url + "/json/list", timeout=3))
            target = next(item for item in targets if item.get("type") == "page" and item.get("url") == start_url)
            cdp = _CDP(target["webSocketDebuggerUrl"])
            for _ in range(30):
                if cdp.evaluate("document.readyState === 'complete' && !!document.querySelector('#fixture-field')"):
                    break
                time.sleep(.1)
            self.assertTrue(cdp.evaluate("document.readyState === 'complete' && !!document.querySelector('#fixture-field')"))
            self.assertTrue(cdp.evaluate(browser_tools._FINAL_GUARD_JS))
            guard_probe = cdp.evaluate("""(() => ({
              installed: window.__chironFinalGuardInstalled === true,
              version: window.__chironFinalGuardState?.version,
              click: (getEventListeners(document).click || []).filter(x => String(x.listener).includes('__chironBlockedFinalAction')).length,
              submit: (getEventListeners(document).submit || []).filter(x => String(x.listener).includes('__chironBlockedFinalAction')).length
            }))()""")
            self.assertEqual(guard_probe, {"installed": True, "version": 5, "click": 1, "submit": 1})
            self.store.bind_attempt_target(
                "att-one", worker_id="worker-one", target_id=target["id"], start_url=start_url,
            )
            review = self.store.publish_review("att-one", {
                "stage": "review", "url": start_url, "target_id": target["id"],
                "observed_resume_sha256": self.store.attempt_context("att-one")["resume_sha256"],
                "rendered": {"synthetic_fixture": True}, "provisional": [],
                "final_actions": ["Submit Application"], "submit_untouched": True,
                "final_guard_active": True,
            }, profile_name=worker.hermes_profile)

            password_hash = bcrypt.hashpw(b"fixture-password", bcrypt.gensalt(rounds=4)).decode()
            environment = patch.dict(os.environ, {
                "CHIRONJP_REVIEW_USERNAME": "owner",
                "CHIRONJP_REVIEW_PASSWORD_HASH": password_hash,
            })
            environment.start()
            self.addCleanup(environment.stop)
            review_server = ReviewServer(
                ("127.0.0.1", 0), self.store, self.registry, Path("/usr/share/novnc"),
            )
            review_thread = threading.Thread(target=review_server.serve_forever, daemon=True)
            review_thread.start()
            origin = f"http://127.0.0.1:{review_server.server_address[1]}"
            path = f"/reviews/{review['review_id']}/desktop/{_token(_review_tab(review))}/"
            socket_url = "ws" + origin.removeprefix("http") + path + "socket?session=phone-fixture"
            with self.assertRaises(InvalidStatus):
                connect(socket_url, origin=origin, subprotocols=["binary"])

            login = Request(
                origin + "/login",
                data=urlencode({"username": "owner", "password": "fixture-password"}).encode(),
                headers={"Origin": origin}, method="POST",
            )
            try:
                build_opener(NoRedirect()).open(login)
            except HTTPError as response:
                self.assertEqual(response.code, 303)
                cookie = response.headers["Set-Cookie"].split(";", 1)[0]
            else:
                self.fail("login redirect unexpectedly followed")
            websocket = connect(
                socket_url, origin=origin, subprotocols=["binary"],
                additional_headers={"Cookie": cookie}, max_size=24 * 1024 * 1024,
            )

            buffered = bytearray()
            def receive(count):
                while len(buffered) < count:
                    message = websocket.recv(timeout=5)
                    buffered.extend(message.encode("latin1") if isinstance(message, str) else message)
                result = bytes(buffered[:count])
                del buffered[:count]
                return result

            self.assertEqual(receive(12), b"RFB 003.008\n")
            websocket.send(b"RFB 003.008\n")
            security_count = receive(1)[0]
            security_types = receive(security_count)
            self.assertIn(1, security_types)
            websocket.send(b"\x01")
            self.assertEqual(receive(4), b"\x00\x00\x00\x00")
            websocket.send(b"\x01")
            server_init = receive(24)
            receive(struct.unpack(">I", server_init[20:24])[0])

            def transition(action):
                request = Request(
                    origin + path + action + "?session=phone-fixture", data=b"",
                    headers={"Origin": origin, "Cookie": cookie, "X-ChironJP-Desktop": "1"},
                    method="POST",
                )
                try:
                    with urlopen(request, timeout=15) as response:
                        payload = json.load(response)
                except HTTPError as response:
                    payload = json.load(response)
                if not payload.get("ok"):
                    self.fail(f"control transition failed: {payload}")
                return payload

            self.assertEqual(transition("take")["state"], "controlling")
            time.sleep(.5)
            view_only = subprocess.run(
                ["x11vnc", "-display", worker.x_display, "-Q", "viewonly"],
                capture_output=True, text=True, check=True, timeout=5,
            )
            self.assertIn("ans=viewonly:0", view_only.stdout + view_only.stderr)
            point = cdp.evaluate("""(() => {const r=document.querySelector('#fixture-field').getBoundingClientRect();return {
              x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2+(window.outerHeight-window.innerHeight))}})()""")
            websocket.send(struct.pack(">BBHH", 5, 0, point["x"], point["y"]))
            websocket.send(struct.pack(">BBHH", 5, 1, point["x"], point["y"]))
            websocket.send(struct.pack(">BBHH", 5, 0, point["x"], point["y"]))
            for _ in range(20):
                if cdp.evaluate("document.activeElement?.id") == "fixture-field":
                    break
                time.sleep(.1)
            self.assertEqual(cdp.evaluate("document.activeElement?.id"), "fixture-field")
            websocket.send(struct.pack(">BB2xI", 4, 1, ord("x")))
            websocket.send(struct.pack(">BB2xI", 4, 0, ord("x")))
            for _ in range(30):
                if cdp.evaluate("document.querySelector('#fixture-field').value") == "x":
                    break
                time.sleep(.1)
            self.assertEqual(cdp.evaluate("document.querySelector('#fixture-field').value"), "x")
            self.assertEqual(transition("return")["state"], "view_only")
            self.assertTrue(cdp.evaluate("window.__chironFinalGuardInstalled === true"))
            websocket.send(struct.pack(">BB2xI", 4, 1, ord("y")))
            websocket.send(struct.pack(">BB2xI", 4, 0, ord("y")))
            time.sleep(.3)
            self.assertEqual(cdp.evaluate("document.querySelector('#fixture-field').value"), "x")
        finally:
            if websocket is not None:
                websocket.close()
            if cdp is not None:
                cdp.close()
            if review_server is not None:
                review_server.shutdown(); review_server.server_close()
            if review_thread is not None:
                review_thread.join(timeout=5)
            if browser_started:
                try:
                    stop_chromium(worker)
                except RuntimeError:
                    pass
                try:
                    stop_surface(worker)
                except RuntimeError:
                    pass
                # Failed assertions must not leak any process started from this
                # disposable worker. Each pidfile is confined to its temp root.
                for pid_path in [worker.workspace / "chromium.pid", *sorted((worker.workspace / "takeover").glob("*.pid"))]:
                    try:
                        pid = int(pid_path.read_text().strip())
                        os.killpg(pid, signal.SIGTERM)
                    except (OSError, ValueError):
                        continue
            page.shutdown(); page.server_close(); page_thread.join(timeout=5)

    @unittest.skipUnless(os.environ.get("CHIRONJP_PHONE_NOVNC_INTEGRATION") == "1", "phone-sized HTTPS/noVNC integration is opt-in")
    def test_phone_https_page_novnc_keyboard_scroll_return_and_reconnect(self):
        try:
            import bcrypt
            import websockify.websocket  # noqa: F401
        except ImportError as exc:
            self.skipTest(f"optional Review transport dependency unavailable: {exc}")
        if not all(shutil.which(name) for name in ("chromium", "Xvfb", "x11vnc", "websockify", "openssl")):
            self.skipTest("Chromium/Xvfb/x11vnc/websockify/OpenSSL are required")
        if not Path("/usr/share/novnc/core/rfb.js").is_file():
            self.skipTest("noVNC web assets are required")

        page = ThreadingHTTPServer(("127.0.0.1", 0), FixturePage)
        page_thread = threading.Thread(target=page.serve_forever, daemon=True)
        page_thread.start()
        start_url = f"http://127.0.0.1:{page.server_address[1]}/application"
        worker = self.registry.worker("worker-one")
        review_server = None
        review_thread = None
        remote_started = False
        remote_cdp = None
        phone_process = None
        phone_cdp = None
        try:
            with self.store.immediate() as connection:
                connection.execute(
                    "UPDATE applications SET start_url=?,tenant_host='127.0.0.1' WHERE id='app-one'",
                    (start_url,),
                )
                connection.execute(
                    "UPDATE attempts SET designated_target_id=NULL,designated_start_url=NULL,designated_at=NULL,target_last_url=NULL WHERE id='att-one'",
                )
            start_chromium(self.registry, worker, initial_url=start_url)
            remote_started = True
            targets = json.load(urlopen(worker.cdp_url + "/json/list", timeout=3))
            target = next(item for item in targets if item.get("type") == "page" and item.get("url") == start_url)
            remote_cdp = _CDPConnection(target["webSocketDebuggerUrl"])

            def wait_for(predicate, message, attempts=100):
                for _ in range(attempts):
                    try:
                        value = predicate()
                    except TimeoutError:
                        # A page navigation can briefly delay a CDP evaluation;
                        # the same exact target remains bound and is retried.
                        value = False
                    if value:
                        return value
                    time.sleep(.1)
                self.fail(message)

            wait_for(
                lambda: remote_cdp.js("document.readyState === 'complete' && !!document.querySelector('#phone-fixture-field')"),
                "fictional remote application did not load",
            )
            self.assertTrue(remote_cdp.js(browser_tools._FINAL_GUARD_JS))
            self.store.bind_attempt_target(
                "att-one", worker_id="worker-one", target_id=target["id"], start_url=start_url,
            )
            review = self.store.publish_review("att-one", {
                "stage": "review", "url": start_url, "target_id": target["id"],
                "observed_resume_sha256": self.store.attempt_context("att-one")["resume_sha256"],
                "rendered": {"synthetic_phone_fixture": True}, "provisional": [],
                "final_actions": ["Submit Application"], "submit_untouched": True,
                "final_guard_active": True,
            }, profile_name=worker.hermes_profile)

            password_hash = bcrypt.hashpw(b"fixture-password", bcrypt.gensalt(rounds=4)).decode()
            environment = patch.dict(os.environ, {
                "CHIRONJP_REVIEW_USERNAME": "owner",
                "CHIRONJP_REVIEW_PASSWORD_HASH": password_hash,
            })
            environment.start()
            self.addCleanup(environment.stop)
            review_server = ReviewServer(
                ("127.0.0.1", 0), self.store, self.registry, Path("/usr/share/novnc"),
            )
            certificate = self.root / "fixture-cert.pem"
            private_key = self.root / "fixture-key.pem"
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
                "-keyout", str(private_key), "-out", str(certificate),
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.load_cert_chain(certificate, private_key)
            review_server.socket = tls.wrap_socket(review_server.socket, server_side=True)
            review_thread = threading.Thread(target=review_server.serve_forever, daemon=True)
            review_thread.start()
            origin = f"https://127.0.0.1:{review_server.server_address[1]}"

            phone_profile = self.root / "phone-profile"
            phone_log = self.root / "phone-chromium.log"
            with phone_log.open("wb") as log:
                phone_process = subprocess.Popen([
                    shutil.which("chromium"), "--headless=new", "--no-sandbox", "--disable-gpu",
                    "--ignore-certificate-errors", "--no-first-run", "--disable-sync",
                    "--disable-background-networking", "--disable-dev-shm-usage",
                    "--remote-debugging-port=0", "--window-size=390,844",
                    f"--user-data-dir={phone_profile}", origin + "/reviews",
                ], stdout=log, stderr=log)
            debugger_marker = phone_profile / "DevToolsActivePort"
            debugger_lines = []
            for _ in range(300):
                if debugger_marker.is_file():
                    debugger_lines = debugger_marker.read_text(encoding="ascii").splitlines()
                    if debugger_lines and debugger_lines[0].isdigit():
                        break
                if phone_process.poll() is not None:
                    self.fail(f"phone Chromium exited early: {phone_log.read_text(errors='replace')[-2000:]}")
                time.sleep(.1)
            else:
                self.fail(f"phone Chromium did not expose CDP: {phone_log.read_text(errors='replace')[-2000:]}")
            phone_endpoint = "http://127.0.0.1:" + debugger_lines[0]
            phone_target = None
            for _ in range(60):
                try:
                    phone_targets = json.load(urlopen(phone_endpoint + "/json/list", timeout=1))
                    phone_target = next(
                        (item for item in phone_targets if item.get("type") == "page" and str(item.get("url", "")).startswith(origin)),
                        None,
                    )
                    if phone_target is not None:
                        break
                except (OSError, TimeoutError):
                    pass
                time.sleep(.1)
            if phone_target is None:
                self.fail(f"phone Chromium did not open the Review URL: {phone_log.read_text(errors='replace')[-2000:]}")
            phone_cdp = PhoneCDPConnection(phone_target["webSocketDebuggerUrl"])
            phone_cdp.call(
                "Emulation.setDeviceMetricsOverride", width=390, height=844,
                deviceScaleFactor=1, mobile=True,
            )

            def phone_js(expression):
                return phone_cdp.js(expression)

            def phone_click(selector):
                point = phone_js(f"""(() => {{const e=document.querySelector({json.dumps(selector)});
                  if(!e) return null;e.scrollIntoView({{block:'center'}});const r=e.getBoundingClientRect();
                  return {{x:r.left+r.width/2,y:r.top+r.height/2}}}})()""")
                self.assertIsNotNone(point, f"missing rendered control: {selector}")
                phone_cdp.click(point["x"], point["y"])

            wait_for(lambda: phone_js("document.querySelector('form[action=\"/login\"]') !== null"), "rendered sign-in form did not load")
            self.assertEqual(phone_js("({width:innerWidth,height:innerHeight})"), {"width": 390, "height": 844})
            phone_click("input[name=username]")
            phone_cdp.call("Input.insertText", text="owner")
            phone_click("input[name=password]")
            phone_cdp.call("Input.insertText", text="fixture-password")
            phone_click("button")
            wait_for(lambda: phone_js("location.pathname === '/reviews' && !!document.querySelector('a.card')"), "normal HTTPS sign-in did not reach Reviews")
            cookies = phone_cdp.call("Network.getCookies", urls=[origin])["cookies"]
            owner_cookie = next(item for item in cookies if item["name"] == "chironjp_owner_session")
            self.assertTrue(owner_cookie["secure"])
            self.assertTrue(owner_cookie["httpOnly"])

            phone_click("a.card")
            wait_for(lambda: phone_js("!!document.querySelector('a[href*=\"/desktop/\"]')"), "retained Review detail did not render")
            phone_click("a[href*='/desktop/']")
            desktop_state = None
            for _ in range(150):
                desktop_state = phone_js("""(() => {const take=document.querySelector('#take'),status=document.querySelector('#status')?.textContent||'';
                  return {status,takeDisabled:take?.disabled,canvas:!!document.querySelector('#screen canvas')}})()""")
                if ("view-only" in desktop_state["status"] and desktop_state["takeDisabled"] is False) or "Disconnected" in desktop_state["status"]:
                    break
                time.sleep(.1)
            else:
                self.fail(f"shipped desktop.js/noVNC did not connect view-only: {desktop_state}")
            self.assertIn("view-only", desktop_state["status"], desktop_state)
            self.assertFalse(desktop_state["takeDisabled"], desktop_state)
            assets = phone_cdp.call("Performance.getMetrics").get("metrics", [])
            self.assertTrue(assets is not None)  # Page has an active renderer before interaction.
            self.assertTrue(phone_js("!!document.querySelector('#screen canvas')"))
            wait_for(lambda: phone_js("document.querySelector('#screen canvas')?.width > 0"), "noVNC framebuffer did not initialize")

            phone_click("#take")
            wait_for(lambda: phone_js("document.querySelector('#status')?.textContent.includes('You have control')"), "Take control did not complete", 150)
            self.assertFalse(phone_js("document.querySelector('#keyboard').disabled"))
            time.sleep(.5)

            def phone_tap(point):
                phone_cdp.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[
                    {"x": point["x"], "y": point["y"], "id": 1},
                ])
                phone_cdp.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])

            first_remote_point = remote_cdp.js("""(() => {const r=document.querySelector('h1').getBoundingClientRect();
              return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2+(outerHeight-innerHeight))}})()""")
            first_phone_point = phone_js(f"""(() => {{const c=document.querySelector('#screen canvas'),r=c.getBoundingClientRect();
              return {{x:r.left+({first_remote_point['x']}/c.width)*r.width,y:r.top+({first_remote_point['y']}/c.height)*r.height}}}})()""")
            phone_tap(first_phone_point)
            wait_for(lambda: remote_cdp.js("window.fixtureClicks.some(item => item.tag === 'H1' && item.trusted)"), "noVNC pointer did not reach the visible fictional page")
            self.assertEqual(remote_cdp.js("document.activeElement?.tagName"), "H1")
            for _ in range(3):
                phone_click("#page-down")
                time.sleep(.15)
            wait_for(
                lambda: remote_cdp.js("scrollY > 150"),
                f"noVNC scroll did not move the retained remote page; keys={remote_cdp.js('window.fixtureKeys')}",
            )

            remote_point = remote_cdp.js("""(() => {const r=document.querySelector('#phone-fixture-field').getBoundingClientRect();
              return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2+(outerHeight-innerHeight))}})()""")
            phone_point = phone_js(f"""(() => {{const c=document.querySelector('#screen canvas'),r=c.getBoundingClientRect();
              return {{x:r.left+({remote_point['x']}/c.width)*r.width,y:r.top+({remote_point['y']}/c.height)*r.height}}}})()""")
            phone_tap(phone_point)
            wait_for(lambda: remote_cdp.js("document.activeElement?.id === 'phone-fixture-field'"), "phone pointer did not focus the remote fictional field")

            phone_click("#keyboard")
            self.assertTrue(phone_js("document.activeElement?.id === 'keyboard'"))
            self.assertTrue(phone_js("document.querySelector('#insert').disabled"))
            phone_cdp.call("Input.insertText", text="typed ")
            self.assertEqual(phone_js("document.querySelector('#keyboard').value"), "typed ")

            # Use Chromium's native copy/paste path, then separately deliver a
            # null-data paste-shaped input event. The composer logic depends
            # only on its current value, so neither case clears or forwards it.
            phone_js("""(() => {const source=document.createElement('input');source.id='fixture-paste-source';
              source.value='pasted text';document.body.append(source);source.select();
              window.__fixtureComposerEvents=[];document.querySelector('#keyboard').addEventListener('input',event=>
                window.__fixtureComposerEvents.push({inputType:event.inputType,data:event.data}));})()""")

            def shortcut(letter, virtual_key):
                phone_cdp.call(
                    "Input.dispatchKeyEvent", type="rawKeyDown", key="Control", code="ControlLeft",
                    modifiers=2, windowsVirtualKeyCode=17, nativeVirtualKeyCode=17,
                )
                phone_cdp.call(
                    "Input.dispatchKeyEvent", type="rawKeyDown", key=letter, code="Key" + letter.upper(),
                    modifiers=2, windowsVirtualKeyCode=virtual_key, nativeVirtualKeyCode=virtual_key,
                )
                phone_cdp.call(
                    "Input.dispatchKeyEvent", type="keyUp", key=letter, code="Key" + letter.upper(),
                    modifiers=2, windowsVirtualKeyCode=virtual_key, nativeVirtualKeyCode=virtual_key,
                )
                phone_cdp.call(
                    "Input.dispatchKeyEvent", type="keyUp", key="Control", code="ControlLeft",
                    modifiers=0, windowsVirtualKeyCode=17, nativeVirtualKeyCode=17,
                )

            shortcut("c", 67)
            phone_js("document.querySelector('#fixture-paste-source').remove()")
            phone_click("#keyboard")
            phone_js("""(() => {const input=document.querySelector('#keyboard');
              input.setSelectionRange(input.value.length,input.value.length)})()""")
            shortcut("v", 86)
            composed = "typed pasted text"
            wait_for(lambda: phone_js(f"document.querySelector('#keyboard').value === {json.dumps(composed)}"), "native paste was not retained visibly in the phone composer")
            self.assertTrue(phone_js("window.__fixtureComposerEvents.some(event => event.inputType === 'insertFromPaste')"))
            self.assertEqual(phone_js("""(() => {const input=document.querySelector('#keyboard');
              input.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertFromPaste',data:null}));
              return input.value})()"""), composed)
            self.assertEqual(remote_cdp.js("document.querySelector('#phone-fixture-field').value"), "")
            self.assertFalse(phone_js("document.querySelector('#insert').disabled"))
            phone_click("#insert")
            wait_for(lambda: remote_cdp.js(f"document.querySelector('#phone-fixture-field').value === {json.dumps(composed)}"), "explicit Insert did not send the complete composer value once")
            self.assertEqual(phone_js("document.querySelector('#keyboard').value"), composed)
            self.assertTrue(phone_js("document.querySelector('#insert').disabled"))
            phone_click("#insert")
            time.sleep(.3)
            self.assertEqual(remote_cdp.js("document.querySelector('#phone-fixture-field').value"), composed)

            proof_dir = Path(__file__).parents[1] / "runtime" / "proof"
            proof_dir.mkdir(parents=True, exist_ok=True)
            captured = []
            def capture(name):
                path = proof_dir / name
                encoded = phone_cdp.call("Page.captureScreenshot", format="png", fromSurface=True)["data"]
                path.write_bytes(base64.b64decode(encoded))
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertGreater(path.stat().st_size, 10_000)
                captured.append((path, digest))

            capture("phone-novnc-control-fictional.png")

            phone_click("#release")
            wait_for(lambda: phone_js("document.querySelector('#status')?.textContent.includes('control returned')"), "Return control was not verified", 150)
            self.assertTrue(remote_cdp.js("window.__chironFinalGuardInstalled === true"))
            self.assertEqual(remote_cdp.js("window.fixtureFinalActivations"), 0)

            prior_generation = next(iter(review_server.desktop_connections.values()))["generation"]
            phone_cdp.call("Page.reload", ignoreCache=True)
            wait_for(lambda: phone_js("""(() => {const take=document.querySelector('#take'),status=document.querySelector('#status')?.textContent||'';
              return status.includes('view-only') && take?.disabled===false})()"""), "reloaded desktop did not reconnect view-only", 150)
            wait_for(
                lambda: next(iter(review_server.desktop_connections.values()), {}).get("generation") not in {None, prior_generation},
                "desktop reload did not establish a replacement connection generation",
            )
            self.assertEqual(remote_cdp.js("document.querySelector('#phone-fixture-field').value"), composed)
            self.assertEqual(remote_cdp.js("window.fixtureFinalActivations"), 0)
            self.assertTrue(phone_js("document.querySelector('#keyboard').disabled"))
            phone_js("window.scrollTo(0,0)")
            capture("phone-novnc-reconnected-fictional.png")
            for screenshot_path, screenshot_sha256 in captured:
                print(f"PHONE_NOVNC_FIXTURE_SCREENSHOT={screenshot_path} SHA256={screenshot_sha256}")
        finally:
            if phone_cdp is not None:
                phone_cdp.close()
            if phone_process is not None:
                phone_process.terminate()
                try:
                    phone_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    phone_process.kill(); phone_process.wait(timeout=5)
            if review_server is not None:
                review_server.shutdown(); review_server.server_close()
            if review_thread is not None:
                review_thread.join(timeout=5)
            if remote_cdp is not None:
                remote_cdp.close()
            if remote_started:
                try:
                    stop_chromium(worker)
                except RuntimeError:
                    pass
                try:
                    stop_surface(worker)
                except RuntimeError:
                    pass
                for pid_path in [worker.workspace / "chromium.pid", *sorted((worker.workspace / "takeover").glob("*.pid"))]:
                    try:
                        pid = int(pid_path.read_text().strip())
                        os.killpg(pid, signal.SIGTERM)
                    except (OSError, ValueError):
                        continue
            page.shutdown(); page.server_close(); page_thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
