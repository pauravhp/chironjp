---
name: chiron-application-executor
description: Prepare one isolated employer application to verified guarded Review and retain it for human final action.
---

# Chiron application executor

Use only the supplied run brief, canonical profile, package artifacts, and
assigned browser workspace. Never inspect another worker workspace. Confirm the
live target matches the brief before any browser side effect.

Guarded Review is the success condition. Submit, Send, Confirm, and every
semantically equivalent final action belong to the human owner in the rendered
employer interface. Never import or construct a final-click or guard-disarm
helper. Tests and fixtures are not evidence of delivery or submission.

## Observe before acting

Use the controller-installed `browser-harness==0.1.9` runtime. Import
`agent_helpers` in each stateless browser execution. Call
`ats_observe(js, ats_family)` on the exact target and require
`final_guard_active` before activating any control. An unsupported family means
the compact inventory is unavailable; it does not disable the universal guard
or ordinary Browser Harness inspection.

Use the bundled [browser helper quick reference](references/browser-contract.md)
for the exact workspace-local helper signatures.

Invoke the exact executable supplied in `CHIRONJP_BROWSER_HARNESS`; do not pick
a repository or shared virtual environment. Preserve the controller-supplied
`BU_CDP_URL` and Browser Harness runtime-directory environment on every call so
the attempt cannot attach to another daemon or browser; do not add or override
`BU_NAME`. The controller has already bound that daemon to the brief's exact target and
proved `Runtime.evaluate`. Do not reset a healthy transport, create a replacement
tab, or substitute another target. On demonstrated transport failure, recover
only this worker's isolated daemon, then rebind and verify the same target
before continuing.

For an attached frame, use the exact CDP session id. Never pass a frame target
id as if it routed Runtime, DOM, Page, or Input commands. Never use document or
frame-local coordinates as top-level viewport coordinates.

Use only owner-confirmed canonical facts. Sensitive facts stay unset until the
owner supplies or authorizes them; never infer them. When authorized, canonical
answers such as a name/signature or demographic preference can be filled like
ordinary fields. Only evidence-required human authentication, CAPTCHA, consent,
and the final action require the owner.

## Prepare and verify

- Use `trusted_batch_input` for exact text-like values and require an exact
  returned readback.
- Use `exact_select` only when one rendered option exactly matches the canonical
  value. It scrolls and hit-tests the control before trusted opening, then reads
  the rendered value, including React-select values.
- Use `upload_and_verify` for the exact package artifact. Require the returned
  SHA-256 match; a rendered filename alone is insufficient. The helper retains
  change-event bytes when an ATS clears its file input.
- Use `advance` only for one unique `Next`, `Continue`, or `Save and Continue`.
  A generic `Apply` may be ordinary navigation. It is final only when exact
  rendered context identifies it as the application-final action.
- Reinspect after every mismatch. Do not repeat an identical side effect against
  an unchanged page.

## Review

Call `review_readback(js, ats_family, profile, constraints)` with the canonical
profile and employer-rendered constraints.

For Workday, require `structured_history.complete: true` and preserve
`question_answers`. A resume attachment is not structured Experience/Education.
Missing or mismatched rows keep the stage at `application`.

For Greenhouse, a visible Submit Application control is insufficient. All
observable required fields/groups must be complete and rendered validation must
be clear before the stage can be `review`.

Record only secret-free rendered Review evidence, the exact package hash, and
the exact retained target id. Keep the target open. Yield to the controller for
authenticated human takeover; the controller pauses browser input, changes the
VNC surface, transfers/restores the guard, and later decides whether a rendered
human outcome is sufficient.
