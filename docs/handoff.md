# Human browser handoff

`chironjp/handoff.py` is the controller-owned bridge between a guarded browser
worker and an authenticated human Review session. It is not a browser-worker
tool, is not installed in the Hermes executor skill, and has no CLI. It never
performs a final action. Its only privileged operation is temporarily removing
Chiron's own final-action guard so the authenticated owner can use the retained
employer interface directly.

## Exact control sequence

The Review edge must first authenticate the owner, enforce same-origin transport
rules, and bind its opaque connection ID with `register_connected_owner`. That
registration is a capability boundary, not an authentication implementation.
Do not expose it to Hermes or an untrusted HTTP route.

`take_control` then performs one serialized, worker-specific transition:

1. require the connected session's binding to match the application, worker,
   browser profile, CDP target, and retained-target opening time;
2. create a private control marker, find only processes carrying the exact
   application identity or the worker's exact Browser Harness runtime identity,
   send `SIGSTOP`, and verify the Linux process state;
3. verify and activate the exact retained page target;
4. remove only listeners containing Chiron's guard marker in that page and its
   directly owned frame targets, restore the guard-captured native
   `HTMLFormElement.submit`, and install trusted human edit/click observation;
5. require every inspected realm to prove the guard listener is absent and the
   human observer is active;
6. verify the worker-owned x11vnc PID and only then issue `noviewonly`.

`return_control` first requests x11vnc `viewonly`, reinstalls the same versioned
guard in every inspected realm, captures a screenshot after masking visible
one-time-code inputs, and verifies the guard before any producer resumes.
Browser Harness processes are terminated because their cached coordinates may
be stale; other exact-application producers receive `SIGCONT`. If input disable
or guard verification fails, the ownership marker remains and producers remain
paused. `observe_control` checks the same exact binding and requires the human
handoff state to remain consistent.

This module does not make a bare noVNC endpoint safe. VNC/noVNC/CDP listeners
must remain private. `chironjp/review_server.py` supplies the loopback Review
edge: password authentication, same-origin HTTP/WebSocket checks, and an
authenticated binary WebSocket proxy to the worker's private VNC listener. Put
that loopback edge behind the operator's authenticated HTTPS tunnel; do not
publish the worker ports.

Each socket keeps the immutable Review, tab, and worker identity it authenticated.
A per-session connection generation covers the complete disconnect return,
guard restoration, and capability-unregistration lifecycle. Reloading replaces
the socket atomically: cleanup from the old socket cannot return or unregister
the replacement. Failed Return or disconnect cleanup is recorded without
discarding the active human-session marker. The JSON response and browser UI
report an uncertain state and retain a Return-control retry instead of claiming
that the guard was restored.

The desktop remains visible in view-only mode. Its local phone-keyboard input
forwards committed Unicode text, Backspace, and Enter through noVNC only while
an authenticated human session is in the verified `controlling` state. The
input is disabled while disconnected, view-only, or uncertain. The owner still
focuses the intended field in the retained employer interface before typing.

## Provenance

This is a sanitized, dependency-closed adaptation of the owner-authorized
Chiron reference revision `faf85660331667338c717c3fee4390913456d22a`.

| Reference location | Public location | Preserved mechanic |
| --- | --- | --- |
| `chiron/desktop.py::_worker_lock`, `binding`, `_control_path`, `_save_control` | same or descriptive names in `chironjp/handoff.py` | per-worker serialization and exact retained-target lease |
| `chiron/desktop.py::_identity`, `_processes`, `_resume_processes` | `_process_identity`, `_application_processes`, `_resume_processes` | PID-start-time ownership, exact producer pause, stale Browser Harness termination |
| `chiron/desktop.py::_browser_control_cdp` | `_browser_control_cdp` | page/owned-frame routing, named guard removal/restoration, trusted human observation, credential masking, screenshot hash |
| `chiron/desktop.py::_vnc_view_only` | `_owned_vnc_pid`, `_set_vnc_view_only` | worker-owned x11vnc view-only/input transition |
| `chiron/desktop.py::control`, `_finish_control_locked`, `observe` | `take_control`, `return_control`, `observe_control` | pause → guard removal → input and input off → guard rearm → resume ordering |

The public adaptation strengthens the reference postconditions by requiring
explicit guard-state results from every inspected CDP session before enabling
input or resuming a producer. Machine paths, Review database coupling, private
records, and deployment-specific transport state were not copied.

## Verification

Run the deterministic controller tests:

```bash
python3 -m unittest -v tests_python.test_handoff.HandoffControllerTests
```

They check exact-session/worker binding, producer pause ordering, guard-state
verification before input, view-only before return, rearm before resume, and
fail-closed behavior.

An opt-in test uses a fresh temporary Chromium profile and a local synthetic
form. It proves that the guard blocks the fixture final control during agent
operation, is absent during owner handoff, and is restored after return:

```bash
CHIRONJP_BROWSER_INTEGRATION=1 .venv/bin/python \
  -m unittest -v tests_python.test_handoff.ChromiumHandoffIntegrationTests
```

Chromium and the Python `websockets` package are required. This isolated fixture
test passed during extraction; it is not application, submission, authenticated
gateway, or real noVNC transport evidence. The remaining gateway proof belongs
in the deployment checklist in `docs/proof.md`.

The Review edge also has an opt-in, dependency-real synthetic transport test:

```bash
CHIRONJP_NOVNC_INTEGRATION=1 .venv/bin/python \
  -m unittest -v \
  tests_python.test_review_flow.ReviewFlowTests.test_real_authenticated_vnc_take_type_and_guarded_return
```

It starts disposable Xvfb, x11vnc, Chromium, and the public Review server. It
proves an anonymous WebSocket denial, authenticated same-origin binary RFB,
Take-control input into an innocuous fictional field, Return-control guard
restoration, and rejection of further VNC input. It never activates the fixture
final control. This test passed on the extraction host. It does not prove a
phone-sized browser, external TLS/access policy, or an employer application;
those remain deployment proof items.
