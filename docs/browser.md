# Browser preparation contract

ChironJP includes the browser mechanics used to prepare an employer form and
prove its rendered Review state. The agent can navigate, fill owner-authorized
canonical answers, select exact rendered options, attach the package artifact,
and correct validation failures. It cannot perform a final action.

## Extracted implementation

[`chironjp/browser_tools.py`](../chironjp/browser_tools.py) is a sanitized,
dependency-closed extraction from the owner-authorized Chiron reference build at
revision `faf85660331667338c717c3fee4390913456d22a`. The source file was
`chiron/browser_toolbox.py`. The retained mappings are:

| Reference function or constant | Public function or constant | Preserved behavior |
| --- | --- | --- |
| `cdp`, `_FINAL_GUARD_JS` | same names | explicit attached-session routing, rejection of `targetId` pseudo-routing, guard installation in the active realm, and top-level viewport rejection |
| `_OBSERVE_JS`, `_REVIEW_JS`, `_stage`, `workday_observe`, `ats_observe` | same names | compact rendered inventory and guarded stage detection |
| `_readback`, `_click_selector`, `exact_select` | same names | rendered React-select value, trusted scrolled and hit-tested opening, exact option match, and post-selection readback |
| `upload_and_verify`, `verify_upload` | same names | capture of the file-change event before an ATS clears its input plus bounded byte retrieval and SHA-256 comparison |
| `_greenhouse_form_ready`, `review_readback` | same names | required-field/group validation before a Greenhouse form can be called Review |
| `workday_history_readback`, `workday_question_readback`, `review_readback` | same names | canonical profile/constraint reconciliation, structured Experience/Education rows, exact sibling question/answer bindings, and demotion of incomplete Review to `application` |

The extraction deliberately excludes login, mailbox, credential, registration,
password-reset, sourcing, and autonomous final-action helpers. It contains no
candidate profile, application record, browser state, or credential default.

## Browser worker usage

The reproducible fresh-runtime default is
[`browser-harness==0.1.9`](https://pypi.org/project/browser-harness/0.1.9/),
whose immutable source tag is
[`41108b8676d4bdb58b26ab3b079c0b7b0f8f3926`](https://github.com/browser-use/browser-harness/tree/41108b8676d4bdb58b26ab3b079c0b7b0f8f3926).
It is an MIT-licensed runtime dependency (Copyright 2026 Browser Use), not code
vendored into this repository. The root third-party notice records that runtime
dependency and its license. The helper requires the documented
`browser_harness.helpers` callback and stateless `agent_helpers.py` surfaces.
An existing runtime with another version is untested, not automatically
incompatible: retain it when the dependency checker and focused browser smoke
prove those surfaces. Do not silently upgrade a working shared environment.

The runtime installs the helper as `agent_helpers.py` in the single assigned
worker workspace. A Browser Harness invocation imports the helpers and supplies
its own `js`, `fill_input`, `click_at_xy`, and CDP callbacks. Attached iframe
targets must use a real CDP `session_id`; document coordinates or `targetId`
parameters are never silently treated as top-level viewport coordinates.

A safe preparation pass is:

1. Select and verify the exact retained employer target from the run brief.
2. Call `ats_observe(js, family)` immediately; require
   `final_guard_active: true` before any action that can activate a control.
3. Use `trusted_batch_input`, `exact_select`, and `upload_and_verify`; verify all
   returned readbacks and change strategy on a mismatch.
4. Use `advance` only for an exact, unique `Next`, `Continue`, or
   `Save and Continue` control. `Apply` remains ordinary navigation unless the
   rendered ATS context proves it is the final application action.
5. Call `review_readback(js, family, profile, constraints)` with the canonical
   profile and any employer-rendered constraints. Workday Review is not ready
   when structured history is missing or mismatched. Greenhouse Review is not
   ready while any observable required field/group or validation remains.
6. Retain the target for the human owner. Do not click `Submit`, `Send`,
   `Confirm`, or an equivalent final control.

Education readback uses the same canonical schema as the renderer: a row with
`current: true` is verified against `expected_end`; a completed row is verified
against `completed_end`. The browser boundary does not invent a second `end`
field or use a stale value from the inactive end-date key.

Questions about permission, sponsorship, legal status, or other sensitive facts
remain unset unless the owner supplies or authorizes an answer. Owner-confirmed
canonical answers, including an authorized name/signature or demographic
preference, may be filled like other form values. Evidence-required human
authentication, CAPTCHA, consent, and the final action remain with the owner.

## Human takeover boundary

The final guard intentionally blocks both trusted and script-driven final
actions during agent operation, including in attached frame realms. The
controller side is implemented by [`chironjp/handoff.py`](../chironjp/handoff.py)
and documented in [`docs/handoff.md`](handoff.md); an authenticated Review
gateway must call it. Interactive takeover requires this sequence, not a worker
helper:

1. authenticate and bind the owner session to the exact retained target;
2. pause all input producers for that application and verify they stopped;
3. remove only Chiron's named guard listeners in every owned document/frame,
   restore the captured native `HTMLFormElement.submit`, then switch the exact
   x11vnc surface from view-only to input-enabled;
4. record trusted human edit/final-click evidence and deduplicate a rapid second
   activation;
5. switch x11vnc back to view-only, reinstall the guard in every realm, and only
   then resume or replace worker input producers.

No disarm or final-click function is exported by `browser_tools.py`. A noVNC
page that is merely view-only is useful observation, but it is not an interactive
human takeover claim. The controller must prove authentication, exact-target
binding, pause, guard handoff, input enablement, return, and guard restoration.

## Verification

Pure regressions live in `tests_python/test_browser_tools.py`. They cover
frame-session routing, viewport rejection, exact-selection opening and rendered
readback, upload change capture and bounded retrieval, Greenhouse readiness,
Workday structured history/questions, generic `Apply`, and the absence of a
worker final-click API.

`python -m chironjp.browser_proof` is an optional disposable Chromium proof. It
requires Chromium and the `websockets` Python package. It creates a fresh
temporary profile and local data pages, then proves trusted fill, exact select,
byte-verified upload, non-final advancement, ordinary `Apply` usability, final
action blocking, and viewport rejection. Its result is fixture evidence only;
it is never application or delivery evidence.

## Jobops attribution

Workday mechanics retain patterns adapted from
[`yuyao-wang/Jobops`](https://github.com/yuyao-wang/Jobops) at immutable commit
[`643f489936e07494941d58433da82826ed224ae8`](https://github.com/yuyao-wang/Jobops/commit/643f489936e07494941d58433da82826ed224ae8),
especially `adapters/workday.py`: stable stage markers, compact field
projection, exact option selection, input readback, upload verification, and
guarded advancement. Jobops is MIT licensed, copyright 2025 humancto. The full
MIT terms belong in `THIRD_PARTY_NOTICES.md`. This attribution does not imply
sponsorship, endorsement, official status, or affiliation.
