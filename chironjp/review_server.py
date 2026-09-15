"""Authenticated retained-Review inbox and same-origin noVNC handoff."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import mimetypes
import os
import secrets
import select
import socket
import threading
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, quote, urlsplit

from . import handoff
from .paths import REPO_ROOT
from .registry import Registry, load_registry
from .store import Store


COOKIE = "chironjp_owner_session"
COOKIE_SECONDS = 12 * 60 * 60
_LOGGER = logging.getLogger(__name__)


def _page(title: str, body: str) -> bytes:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{html.escape(title)}</title><style>
:root{{--paper:#f7f1e5;--ink:#17201b;--line:#878b83;--muted:#5a625c;color-scheme:light;font-family:system-ui,sans-serif}}
*{{box-sizing:border-box}}body{{margin:0;background:#d9d1c3;color:var(--ink);line-height:1.45}}main{{max-width:72rem;margin:auto;padding:1rem}}
a{{color:inherit}}header,.card,form{{background:var(--paper);border:1px solid var(--line);padding:1rem;margin:.7rem 0}}
h1,h2{{margin:.1rem 0 .6rem}}button,input{{font:inherit;min-height:44px;padding:.55rem;border:1px solid var(--line)}}button{{background:var(--ink);color:var(--paper);font-weight:750}}
.list{{display:grid;gap:.55rem}}.row{{display:grid;grid-template-columns:1fr auto;gap:.8rem;align-items:center;text-decoration:none}}.muted{{color:var(--muted)}}
.controls{{display:flex;flex-wrap:wrap;gap:.5rem}}#screen{{height:65dvh;min-height:300px;background:#17201b}}#screen canvas{{touch-action:none}}#screen.standby canvas{{opacity:.92}}
.phone-input{{display:grid;gap:.3rem;margin:.6rem 0}}#keyboard{{width:100%}}#keyboard:disabled{{opacity:.6}}
@media(max-width:600px){{main{{padding:.55rem}}#screen{{height:58dvh;min-height:260px}}}}
</style></head><body><main>{body}</main></body></html>""".encode()


def _token(tab: Mapping[str, Any]) -> str:
    return handoff.binding(tab)


def _review_tab(review: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "application_id": review["application_id"], "worker_id": review["worker_id"],
        "profile_name": review["profile_name"], "target_id": review["target_id"],
        "opened_at": review["opened_at"],
    }


def _human_outcome(result: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    records: list[Mapping[str, Any]] = []
    for outer in result.get("results", []):
        if not isinstance(outer, Mapping):
            continue
        for item in outer.get("clicks", []):
            if isinstance(item, Mapping):
                records.append(item)
    clicks = [click for item in records for click in item.get("clicks", []) if isinstance(click, Mapping)]
    delivered = [click for click in clicks if not click.get("deduped")]
    snapshots = [item["snapshot"] for item in records if isinstance(item.get("snapshot"), Mapping)]
    edits = sum(int(item.get("edits") or 0) for item in records)
    success = next((item for item in snapshots if item.get("success") and not item.get("notSubmitted")), None)
    attention = next((item for item in snapshots if item.get("invalid") or item.get("errors") or item.get("captcha") or item.get("auth")), None)
    evidence = {
        "trusted_final_clicks": delivered,
        "deduped_final_clicks": sum(1 for click in clicks if click.get("deduped")),
        "trusted_edit_events": edits,
        "rendered_evidence": bool(snapshots),
        "snapshots": snapshots,
    }
    if success and delivered:
        evidence["submission_verified"] = True
        return "submitted", evidence
    if delivered and attention:
        return "form_needs_attention", evidence
    if delivered:
        return "outcome_uncertain", evidence
    return ("edited" if edits else "viewed"), evidence


class ReviewHandler(BaseHTTPRequestHandler):
    server_version = "ChironJPReview/0.1"
    protocol_version = "HTTP/1.1"

    def _credentials(self) -> tuple[str, str]:
        return (
            os.environ.get("CHIRONJP_REVIEW_USERNAME", ""),
            os.environ.get("CHIRONJP_REVIEW_PASSWORD_HASH", ""),
        )

    @staticmethod
    def _cookie_key(password_hash: str) -> bytes:
        return hashlib.sha256(("chironjp-review-cookie-v1:" + password_hash).encode()).digest()

    def _new_cookie(self, username: str, password_hash: str) -> str:
        payload = base64.urlsafe_b64encode(json.dumps(
            [username, int(time.time()) + COOKIE_SECONDS], separators=(",", ":"),
        ).encode()).decode().rstrip("=")
        signature = hmac.new(self._cookie_key(password_hash), payload.encode(), hashlib.sha256).hexdigest()
        return payload + "." + signature

    def _authorized(self) -> bool:
        username, password_hash = self._credentials()
        try:
            supplied = SimpleCookie(self.headers.get("Cookie", ""))[COOKIE].value
            payload, signature = supplied.rsplit(".", 1)
            expected = hmac.new(self._cookie_key(password_hash), payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return False
            subject, expires = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            return bool(username and password_hash) and secrets.compare_digest(str(subject), username) and int(expires) >= int(time.time())
        except Exception:
            return False

    def _same_origin(self) -> bool:
        origin = urlsplit(self.headers.get("Origin", ""))
        return origin.scheme in {"http", "https"} and origin.netloc == self.headers.get("Host")

    def _send(self, status: int, body: bytes, content_type: str = "text/html; charset=utf-8", *, inline: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN" if inline else "DENY")
        frame = "'self'" if inline else "'none'"
        self.send_header("Content-Security-Policy", f"default-src 'none'; script-src 'self'; connect-src 'self'; img-src 'self' data: blob:; style-src 'unsafe-inline'; frame-src 'self'; frame-ancestors {frame}; form-action 'self'; base-uri 'none'")
        if getattr(self, "_issue_cookie", None):
            self.send_header("Set-Cookie", f"{COOKIE}={self._issue_cookie}; Path=/; Max-Age={COOKIE_SECONDS}; Secure; HttpOnly; SameSite=Strict")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: Mapping[str, Any]) -> None:
        self._send(status, json.dumps(payload, separators=(",", ":")).encode(), "application/json")

    def _login(self, notice: str = "") -> None:
        message = f"<p role=status>{html.escape(notice)}</p>" if notice else ""
        self._send(HTTPStatus.UNAUTHORIZED, _page("Sign in · ChironJP", f"""
<header><h1>ChironJP Review</h1><p>Owner-only retained application screens.</p></header>{message}
<form method="post" action="/login"><label>Username <input name="username" autocomplete="username" required></label><br>
<label>Password <input name="password" type="password" autocomplete="current-password" required></label><br>
<button>Sign in</button></form>"""))

    def _resolve(self, review_id: str, token: str):
        review = self.server.store.retained_review(review_id)  # type: ignore[attr-defined]
        if review["live_state"] != "active" or review["closed_at"]:
            raise ValueError("retained application target is unavailable")
        tab = _review_tab(review)
        if not secrets.compare_digest(token, _token(tab)):
            raise ValueError("desktop link expired; reopen the retained Review")
        worker = self.server.registry.worker(str(review["worker_id"]))  # type: ignore[attr-defined]
        return review, tab, worker

    def _desktop(self, parsed, *, post: bool = False) -> None:
        parts = parsed.path.strip("/").split("/")
        if len(parts) not in {4, 5} or parts[0] != "reviews" or parts[2] != "desktop":
            self._send(404, b"Not found", "text/plain"); return
        review_id, token = parts[1], parts[3]
        action = parts[4] if len(parts) == 5 else ""
        try:
            review, tab, worker = self._resolve(review_id, token)
            session = parse_qs(parsed.query).get("session", [""])[0]
            if action == "socket" and not post:
                if not self._same_origin() or not session or len(session) > 80:
                    self._send(403, b"Open this desktop from its retained Review.", "text/plain"); return
                self._proxy_vnc(review_id, token, session, review, tab, worker)
                return
            if post:
                if not self._same_origin() or self.headers.get("X-ChironJP-Desktop") != "1" or action not in {"take", "return", "observe"}:
                    self._json(403, {"ok": False, "state": "uncertain", "error": "Forbidden"}); return
                if not session or len(session) > 80:
                    self._json(403, {"ok": False, "state": "uncertain", "error": "Open this desktop from its retained Review."}); return
                key = (review["application_id"], session)
                connection = self.server.active_connection(key)  # type: ignore[attr-defined]
                if connection is None:
                    self._json(409, {"ok": False, "state": "uncertain", "error": "Live desktop connection is unavailable; reconnect before changing control."}); return
                original_review, original_tab, original_worker = (
                    connection["review"], connection["tab"], connection["worker"]
                )
                try:
                    if action == "take":
                        if key not in self.server.human_sessions:  # type: ignore[attr-defined]
                            session_id = "hrs_" + hashlib.sha256(f"{_token(original_tab)}:{session}:{time.time_ns()}".encode()).hexdigest()[:24]
                            self.server.store.begin_human_review_session(original_review["application_id"], session_id=session_id)  # type: ignore[attr-defined]
                            self.server.human_sessions[key] = session_id  # type: ignore[attr-defined]
                        result = handoff.take_control(self.server.registry, original_tab, original_worker, session=session)  # type: ignore[attr-defined]
                        state = "controlling"
                    elif action == "observe":
                        if key in self.server.human_sessions:  # type: ignore[attr-defined]
                            result = handoff.observe_control(original_tab, original_worker, session=session)
                            state = "controlling"
                        else:
                            result = {"state": "view_only"}
                            state = "view_only"
                    else:
                        result = self._return_session(original_review, original_tab, original_worker, session)
                        state = "view_only"
                    self._json(200, {"ok": True, "state": state, "result": result})
                except (ValueError, RuntimeError, OSError) as exc:
                    self.server.record_control_failure(key, action, exc)  # type: ignore[attr-defined]
                    self._json(409, {"ok": False, "state": "uncertain", "error": str(exc)})
                return
            if action:
                self._send(404, b"Not found", "text/plain"); return
            body = f"""<p><a href="/reviews/{quote(review_id)}">Back to retained Review</a></p>
<header><h1>{html.escape(str(review['company']))}</h1><p>{html.escape(str(review['role']))}</p></header>
<p id="status" role="status">Connected view-only. Take control to pause the worker.</p>
<div class="controls"><button id="take" disabled>Take control</button><button id="release" disabled>Return control</button><button id="page-down" disabled>Page down</button></div>
<div id="screen" class="standby" aria-label="Live retained application desktop"></div>
<div class="phone-input"><label for="keyboard">Phone composer</label>
<input id="keyboard" type="text" inputmode="text" enterkeyhint="done" autocomplete="off" autocapitalize="none" spellcheck="false" disabled aria-describedby="keyboard-help">
<button id="insert" type="button" disabled>Insert text</button>
<span id="keyboard-help" class="muted">After focusing a field in the remote form, type or paste here, review the visible text, then choose Insert text. Available only while you control the retained desktop.</span></div>
<script type="module" src="/desktop.js"></script>"""
            self._send(200, _page("Live desktop · ChironJP", body))
        except (ValueError, RuntimeError, OSError) as exc:
            if post:
                self._json(410, {"ok": False, "state": "uncertain", "error": str(exc)})
            else:
                self._send(410, _page("Desktop unavailable", f"<h1>Desktop unavailable</h1><p>{html.escape(str(exc))}</p>"))

    def _return_session(self, review, tab, worker, session):
        result = handoff.return_control(self.server.registry, tab, worker, session=session)  # type: ignore[attr-defined]
        key = (review["application_id"], session)
        session_id = self.server.human_sessions.pop(key, None)  # type: ignore[attr-defined]
        if session_id and result:
            state, evidence = _human_outcome(result.get("browser") or {})
            shot = (result.get("browser") or {}).get("screenshot") or {}
            self.server.store.finish_human_review_session(  # type: ignore[attr-defined]
                session_id, state=state, evidence=evidence,
                transport={"authenticated_same_origin": True},
                screenshot_path=shot.get("path"), screenshot_sha256=shot.get("sha256"),
            )
        return result

    def _cleanup_proxy(self, key, generation, review, tab, worker, session) -> None:
        # Keep generation ownership through all handoff side effects. A reload
        # cannot register a replacement between old cleanup and unregister.
        with self.server._desktop_lock:  # type: ignore[attr-defined]
            current = self.server.desktop_connections.get(key)  # type: ignore[attr-defined]
            if current is None or current["generation"] != generation:
                return
            if key in self.server.human_sessions:  # type: ignore[attr-defined]
                try:
                    # Cleanup deliberately uses the immutable target authenticated
                    # for this socket. A closed/rebound Review must not redirect it.
                    self._return_session(review, tab, worker, session)
                except (ValueError, RuntimeError, OSError) as exc:
                    self.server.record_control_failure(key, "disconnect_return", exc)  # type: ignore[attr-defined]
            handoff.unregister_connected_owner(session)
            del self.server.desktop_connections[key]  # type: ignore[attr-defined]

    def _proxy_vnc(self, review_id, token, session, review, tab, worker) -> None:
        try:
            from websockify.websocket import WebSocket, WebSocketWantReadError, WebSocketWantWriteError
        except ImportError as exc:
            raise RuntimeError("authenticated VNC proxy requires websockify") from exc
        class BinaryWebSocket(WebSocket):
            def select_subprotocol(self, protocols):
                offered = [value.strip() for value in protocols]
                return "binary" if "binary" in offered else ""

        upstream = socket.create_connection(("127.0.0.1", worker.vnc_port), timeout=5)
        websocket = BinaryWebSocket()
        outgoing: list[bytes] = []
        incoming: list[bytes] = []
        key = (review["application_id"], session)
        generation = ""
        try:
            websocket.accept(self.connection, self.headers)
            self.close_connection = True
            self.connection.setblocking(False)
            upstream.setblocking(False)
            generation, replaced = self.server.open_connection(  # type: ignore[attr-defined]
                key, review=review, tab=tab, worker=worker, connection=self.connection,
            )
            if replaced is not None:
                try:
                    replaced.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            while True:
                self._resolve(review_id, token)
                reads, writes, _ = select.select(
                    [self.connection, upstream],
                    ([self.connection] if outgoing else []) + ([upstream] if incoming else []),
                    [], .25,
                )
                if self.connection in reads or websocket.pending():
                    try:
                        data = websocket.recvmsg()
                        if data is None: break
                        incoming.append(data)
                    except WebSocketWantReadError:
                        pass
                if upstream in reads:
                    data = upstream.recv(65536)
                    if not data: break
                    outgoing.append(data)
                if self.connection in writes:
                    try:
                        websocket.sendmsg(outgoing[0]); outgoing.pop(0)
                    except WebSocketWantWriteError:
                        pass
                if upstream in writes:
                    sent = upstream.send(incoming[0]); incoming[0] = incoming[0][sent:]
                    if not incoming[0]: incoming.pop(0)
        finally:
            if generation:
                self._cleanup_proxy(key, generation, review, tab, worker, session)
            upstream.close()
            try: websocket.close()
            except (OSError, AttributeError): pass
            self.connection.close()

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            self._login(); return
        parsed = urlsplit(self.path)
        if parsed.path.startswith("/desktop-assets/"):
            relative = parsed.path.removeprefix("/desktop-assets/")
            root = self.server.novnc_root  # type: ignore[attr-defined]
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                self._send(404, b"Not found", "text/plain"); return
            self._send(200, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            return
        if parsed.path == "/desktop.js":
            self._send(200, (REPO_ROOT / "chironjp/static/desktop.js").read_bytes(), "text/javascript")
            return
        if "/desktop/" in parsed.path:
            self._desktop(parsed); return
        if parsed.path.endswith("/resume.pdf") and parsed.path.startswith("/reviews/"):
            review_id = parsed.path[len("/reviews/"):-len("/resume.pdf")]
            try:
                path = Path(str(self.server.store.retained_review(review_id)["resume_path"]))  # type: ignore[attr-defined]
                self._send(200, path.read_bytes(), "application/pdf", inline=True)
            except (ValueError, OSError):
                self._send(404, b"Not found", "text/plain")
            return
        if parsed.path in {"/", "/reviews"}:
            rows = self.server.store.list_reviews()  # type: ignore[attr-defined]
            items = "".join(
                f'<a class="card row" href="/reviews/{quote(str(row["review_id"]))}"><span><strong>{html.escape(str(row["role"]))}</strong><br><span class="muted">{html.escape(str(row["company"]))}</span></span><span>{html.escape(str(row["ats_family"]))}</span></a>'
                for row in rows
            ) or '<div class="card">No retained Reviews yet.</div>'
            self._send(200, _page("ChironJP Reviews", f"<header><h1>Retained Reviews</h1><p>Owner-controlled final action.</p></header><section class=list>{items}</section>"))
            return
        if parsed.path.startswith("/reviews/"):
            review_id = parsed.path.removeprefix("/reviews/")
            try:
                review = self.server.store.retained_review(review_id)  # type: ignore[attr-defined]
            except ValueError:
                self._send(404, b"Not found", "text/plain"); return
            tab = _review_tab(review)
            desktop = f"/reviews/{quote(review_id)}/desktop/{_token(tab)}/"
            final_actions = ", ".join(html.escape(str(value)) for value in review["final_actions"])
            body = f"""<p><a href="/reviews">Back to Reviews</a></p><header><h1>{html.escape(str(review['role']))}</h1><p>{html.escape(str(review['company']))} · {html.escape(str(review['location']))}</p></header>
<section class=card><h2>Guarded Review</h2><p>Final controls remain owner-only: {final_actions or 'not recorded'}.</p><p><a href="{desktop}">Open authenticated live desktop</a></p></section>
<section class=card><h2>Exact resume</h2><p>SHA-256 {html.escape(str(review['resume_sha256']))}</p><p><a href="/reviews/{quote(review_id)}/resume.pdf">Open PDF</a></p></section>"""
            self._send(200, _page(str(review["role"]), body))
            return
        self._send(404, b"Not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path == "/login":
            try:
                if not self._same_origin(): raise ValueError
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096: raise ValueError
                form = parse_qs(self.rfile.read(length).decode(), keep_blank_values=True)
                username, password_hash = self._credentials()
                supplied_user = form.get("username", [""])[0]
                supplied_password = form.get("password", [""])[0]
                import bcrypt
                if not username or not password_hash or not secrets.compare_digest(supplied_user, username) or not bcrypt.checkpw(supplied_password.encode(), password_hash.encode()):
                    raise ValueError
                self._issue_cookie = self._new_cookie(username, password_hash)
                self.send_response(303)
                self.send_header("Location", "/reviews")
                self.send_header("Set-Cookie", f"{COOKIE}={self._issue_cookie}; Path=/; Max-Age={COOKIE_SECONDS}; Secure; HttpOnly; SameSite=Strict")
                self.send_header("Content-Length", "0")
                self.end_headers()
            except (ValueError, ImportError):
                self._login("Username or password did not match.")
            return
        if not self._authorized():
            self._login(); return
        if "/desktop/" in parsed.path:
            self._desktop(parsed, post=True); return
        self._send(405, b"Method not allowed", "text/plain")


class ReviewServer(ThreadingHTTPServer):
    def __init__(self, address, store: Store, registry: Registry, novnc_root: Path):
        super().__init__(address, ReviewHandler)
        self.store = store
        self.registry = registry
        self.novnc_root = novnc_root.resolve(strict=True)
        self.human_sessions: dict[tuple[str, str], str] = {}
        self.desktop_connections: dict[tuple[str, str], dict[str, Any]] = {}
        self.control_failures: list[dict[str, str]] = []
        self._desktop_lock = threading.RLock()

    def open_connection(self, key, *, review, tab, worker, connection) -> tuple[str, socket.socket | None]:
        generation = secrets.token_urlsafe(18)
        with self._desktop_lock:
            handoff.register_connected_owner(tab, str(key[1]))
            prior = self.desktop_connections.get(key)
            self.desktop_connections[key] = {
                "generation": generation, "review": dict(review), "tab": dict(tab),
                "worker": worker, "connection": connection,
            }
        return generation, (prior or {}).get("connection")

    def active_connection(self, key):
        with self._desktop_lock:
            return self.desktop_connections.get(key)

    def record_control_failure(self, key, action: str, error: Exception) -> None:
        session_digest = hashlib.sha256(str(key[1]).encode()).hexdigest()[:12]
        record = {
            "application_id": str(key[0]), "session_sha256": session_digest,
            "action": action, "error": str(error), "recorded_at": str(int(time.time())),
        }
        with self._desktop_lock:
            self.control_failures.append(record)
        _LOGGER.error("Review control transition failed: %s", json.dumps(record, separators=(",", ":")))


def serve(*, database: str | Path, registry_path: str | Path, host: str = "127.0.0.1", port: int = 8080, novnc_root: str | Path = "/usr/share/novnc") -> None:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("Review must bind loopback and sit behind an authenticated HTTPS tunnel")
    username = os.environ.get("CHIRONJP_REVIEW_USERNAME", "")
    password_hash = os.environ.get("CHIRONJP_REVIEW_PASSWORD_HASH", "")
    if not username or not password_hash:
        raise ValueError("CHIRONJP_REVIEW_USERNAME and CHIRONJP_REVIEW_PASSWORD_HASH are required")
    registry = load_registry(registry_path)
    if registry.database != Path(database).expanduser().resolve():
        raise ValueError("database does not match registry")
    ReviewServer((host, port), Store(database), registry, Path(novnc_root)).serve_forever()
