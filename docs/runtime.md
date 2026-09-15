# Run the public preview

This is the concrete source-to-Review path included in the public preview. It
uses Chiron's SQLite package/Tailor records, the canonical LaTeX renderer,
dedicated Hermes profiles, isolated Chromium workers, and the authenticated
retained-Review/noVNC edge. It has no autonomous final-submission command.

The commands below assume a clean clone and a separate private workspace. Do
not put candidate data, credentials, generated resumes, browser profiles, or
application records in the clone.

## 1. Install and inspect dependencies

Node 20 or newer is needed for sourcing. Python 3.11 or newer runs the Chiron
core. On a new deployment, create the tested isolated environment:

```bash
npm ci
uv venv --python 3.11 /srv/chiron-runtime/runtime/browser-venv
uv pip install --python /srv/chiron-runtime/runtime/browser-venv/bin/python \
  --editable '.[browser,review]'
```

The preview currently runs from the checkout; the editable install keeps its
public resume/templates, worker skills, and static noVNC assets bound to that
exact revision.

Install Chromium, Xvfb, x11vnc, websockify, noVNC, Tectonic, and the
distribution's maintained `poppler-utils`. Then run the secret-free dependency
inventory with explicit executable paths as needed:

```bash
/srv/chiron-runtime/runtime/browser-venv/bin/python \
  scripts/check_runtime_dependencies.py \
  --browser-python /srv/chiron-runtime/runtime/browser-venv/bin/python \
  --browser-use /srv/chiron-runtime/runtime/browser-venv/bin/browser-use
```

Pins are tested installation defaults, not compatibility gates. A different
existing version is reported as untested and remains usable when the required
API and focused smoke pass. Inventory is not live proof. See
[Runtime dependencies](dependencies.md).

## 2. Initialize private state

```bash
python3 skills/chiron-setup/scripts/setup_state.py init \
  --workspace /srv/chiron-runtime \
  --templates "$PWD/templates" \
  --resume-assets "$PWD/resume"
```

Fill the copied canonical profile, resume bank, and worker registry outside the
clone. In `config/chiron-workers.json`, set `hermes_profile_root` to the direct
`profiles` directory under the explicitly selected Hermes root. Keep at least
two unique worker records; unused workers can remain disabled. The runtime
binds each invocation to the exact profile directory with process-local
`HERMES_HOME` and prepends the Chiron-owned `runtime/browser-venv/bin` to the
browser worker's `PATH`.

Create the named profiles and install only the matching public skill into each
one by immutable release URL. The exact fresh/existing-Hermes commands and
non-clobber checks are in the setup [workflow](../skills/chiron-setup/references/workflow.md).
Ensure the selected Hermes executable is on the Chiron service's `PATH`; never
change another process's sticky profile or global environment.

## 3. Source and ingest roles

The initial public source is a credited adaptation of the a16z Speedrun Talent
provider from career-ops. It emits normalized NDJSON and does not score roles or
write application state:

```bash
node bin/chironjp-sourcing.mjs --query 'software engineer' --max-pages 2 \
  > /srv/chiron-runtime/source-jobs.ndjson

/srv/chiron-runtime/runtime/browser-venv/bin/chironctl ingest \
  --database /srv/chiron-runtime/runtime/chiron.sqlite3 \
  --input /srv/chiron-runtime/source-jobs.ndjson

/srv/chiron-runtime/runtime/browser-venv/bin/chironctl jobs \
  --database /srv/chiron-runtime/runtime/chiron.sqlite3
```

Ingress retains the official application identity and deduplicates a repeated
source or apply URL. Select an owner-approved source row before continuing.

## 4. Tailor and admit one package

Create an immutable request bound to the exact source row, profile, bank, and
template hashes, then let the dedicated non-browser Tailor choose canonical
IDs, render the PDF, validate it, inspect the exact PNG, and admit its evidence:

```bash
/srv/chiron-runtime/runtime/browser-venv/bin/chironctl tailor-request \
  --database /srv/chiron-runtime/runtime/chiron.sqlite3 \
  --source SOURCE_ROW_ID \
  --profile /srv/chiron-runtime/config/canonical-profile-overrides.json \
  --bank /srv/chiron-runtime/resume/bank.json \
  --template /srv/chiron-runtime/resume/template.tex

/srv/chiron-runtime/runtime/browser-venv/bin/chironctl tailor-run \
  --database /srv/chiron-runtime/runtime/chiron.sqlite3 \
  --registry /srv/chiron-runtime/config/chiron-workers.json \
  --request REQUEST_ID

/srv/chiron-runtime/runtime/browser-venv/bin/chironctl package-admit \
  --database /srv/chiron-runtime/runtime/chiron.sqlite3 \
  --source SOURCE_ROW_ID --artifact ARTIFACT_ID
```

`tailor-finish` rejects validation/vision files from another request even when
they sit under the Tailor workspace. A unit fixture is not visual inspection;
the Tailor must inspect the exact PNG named and hashed by the passing
validation.

## 5. Prepare and retain the employer form

Claim the package on one enabled worker:

```bash
/srv/chiron-runtime/runtime/browser-venv/bin/chironctl browser-run \
  --database /srv/chiron-runtime/runtime/chiron.sqlite3 \
  --registry /srv/chiron-runtime/config/chiron-workers.json \
  --package PACKAGE_ID --worker worker-a
```

The runner creates or resumes one exact CDP target for the application, binds
it to the durable attempt, resolves the rendered ATS family, and invokes the
dedicated Hermes browser profile. A worker may use ordinary Apply/navigation
controls. The controller independently verifies the exact target, known
requisition identity, ATS-specific required fields/history, untouched final
action, and active guard before publishing Review. A timed-out or unfulfilled
operator records a terminal failure and can resume the same worker/profile and
surviving target; another worker cannot silently duplicate that draft.

## 6. Authenticate and take human control

The Review service requires an owner username and bcrypt password hash supplied
through the deployment's process-local secret mechanism. It refuses non-loopback
binding:

```bash
/srv/chiron-runtime/runtime/browser-venv/bin/chironctl review-serve \
  --database /srv/chiron-runtime/runtime/chiron.sqlite3 \
  --registry /srv/chiron-runtime/config/chiron-workers.json \
  --host 127.0.0.1 --port 8080
```

Set `CHIRONJP_REVIEW_USERNAME` and `CHIRONJP_REVIEW_PASSWORD_HASH` without
putting the password on a command line or in this repository. Route only this
loopback service through owner-selected HTTPS and access authentication, such
as Cloudflare Access. Never expose CDP, VNC, or the worker-local websockify
ports.

The retained Review page shows the exact resume and live desktop. Take control
pauses that application's producers, removes only Chiron's final guard, and
enables input on the worker-owned VNC process. The phone keyboard forwards to a
field focused in the remote form only while the owner controls the session.
Return control switches VNC back to view-only and re-arms the guard before any
producer can resume. If cleanup cannot prove those postconditions, ownership is
shown as uncertain and Return remains retryable.

The owner—not Hermes, Browser Harness, or Chiron—activates Submit, Send,
Confirm, or any equivalent control that actually transmits the application.

## What this does not prove

This repository contains focused fixture and disposable-browser proofs. They
do not prove employer delivery, hiring outcomes, provider authentication,
Cloudflare policy, or Photon/iMessage delivery. Run the redacted deployment
checks in [the proof matrix](proof.md). Photon remains an optional Hermes
integration requiring an owner-authorized send/receive and reconnect test; it
is not a job source.
