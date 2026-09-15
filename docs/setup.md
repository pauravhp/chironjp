# Chiron setup

Chiron supports a fresh Linux VPS with no Hermes installation and an existing, running Hermes environment. Setup is intentionally resumable: it preserves existing profiles and configuration, records only behavioral proof, and continues from the first incomplete stage.

The operational boundary is simple: Chiron may follow ordinary Apply/navigation controls, tailor a resume, and prepare an actual employer form selected by the owner. The owner reviews the retained page—including through an authenticated phone noVNC session—and activates the evidenced final submission control. That is usually Submit, Send, or Confirm; Apply is human-only only when that specific control itself finally transmits the application.

## Start

Invoke the discoverable `chiron-setup` skill from this repository, or initialize the blank runtime files directly:

```bash
python3 skills/chiron-setup/scripts/setup_state.py init \
  --workspace /srv/chiron-runtime \
  --templates "$PWD/templates" \
  --resume-assets "$PWD/resume"
```

Choose a private workspace appropriate to your machine; `/srv/chiron-runtime` is only an example. Initialization creates missing blank config/bank files plus the value-free LaTeX template, and keeps every existing target unchanged. It does not install Hermes or create accounts without review.

On a rerun:

```bash
python3 skills/chiron-setup/scripts/setup_state.py status \
  --workspace /srv/chiron-runtime
```

Recheck each completed stage's live behavior. If proof no longer holds, mark that stage stale and repair it rather than replacing the whole workspace. The setup skill contains the accepted proof names and recovery rules.

## Candidate data

Fill the actual Chiron files under the private workspace:

- `config/canonical-profile-overrides.json` for typed identity, contact, location, education, authorization, preferences, declarations, demographics, and canonical answers;
- `resume/bank.json` for canonical summaries, experience bullets, projects, leadership, awards, skills, exclusions, and evidence provenance;
- `resume/template.tex`, a value-free layout whose identity/contact/education placeholders are filled only from the explicitly bound canonical profile.

The blank profile template keeps current work authorization separate from future sponsorship and retains guidance for location, relocation, availability, compensation, referral/source, education, distinct demographic categories, consent/attestation, and open-ended responses. Demographics stay unset until the owner supplies or authorizes a canonical choice, which the agent may then fill. Consent or attestations remain human actions when the rendered flow requires the human to perform them. Open-ended drafts may use only facts the owner already confirmed.

Owner-confirmed resume or interview evidence is normalized into the resume bank's `skill_sources`/`skill_evidence`; there is no parallel interview-bank schema. Repository runtime templates contain no personal answers. Filled examples under `examples/fictional/` belong to “Avery Example” at fictional organizations and are for testing only.

Use the repository's `chironjp.resume` path to validate an exact canonical-ID Tailor manifest and render LaTeX to PDF. The fully fictional check/render commands are in [Canonical resume composition](resume.md). Acceptance requires one page, four readable Skills lines, no overflow/clipping/intersections, and a generated PNG. A vision review must inspect that exact PNG and bind its path and hash to the selection/validation; a unit test is not a visual inspection.

Setup files alone do not prove an operational Chiron. In an isolated workspace, take `examples/fictional/jobs.ndjson` through the real normalized source → SQLite ingress/deduplication → package/Tailor → Hermes/isolated Chromium → retained Review → authenticated phone noVNC path. Do not activate the final submission control.

## Runtime roles and secrets

The actual worker registry is `config/chiron-workers.json`: Chiron-owned runtime/state/database paths, the direct `profiles` directory of the explicitly selected Hermes root, at least two unique worker records (unused workers may stay disabled), isolated Hermes/Chromium/workspace identities, and non-conflicting CDP/VNC/noVNC ports and displays. Runtime calls bind the exact named profile directory as process-local `HERMES_HOME`; they do not rely on a sticky default. The current role split is `nous` / `z-ai/glm-5.3-flash` / high for Hermes browser preparation, and `openai-codex` / `gpt-5.6-terra` / high for Tailor. Verify access before filling the private config. Public defaults remain blank, and no Codex-only replacement is claimed as proven.

On a fresh VPS—or an existing VPS without Chiron—create new dedicated Hermes profiles rather than modifying `default` or another shared profile. Hermes' supported profile-scoped form is `hermes -p PROFILE COMMAND`. Install the public `worker/skills/chiron-resume-tailor` skill only into the dedicated Tailor profile and `worker/skills/chiron-application-executor` only into dedicated browser profiles, using immutable public `SKILL.md` URLs with `hermes -p PROFILE skills install URL --yes`. Verify with `hermes -p PROFILE skills list --enabled-only`; use `--skills NAME` to preload the already-installed role skill on its worker invocation. The exact commands and safe rerun rules are in the setup skill's [workflow](../skills/chiron-setup/references/workflow.md).

For a new isolated browser runtime, `browser-harness==0.1.9` and
`browser-use==0.13.8` are the tested installation defaults. An existing
runtime may use another version when the required helper APIs and focused
browser smoke pass; report it as untested rather than replacing it solely for
the version number. Do not install or upgrade these packages in a shared
Hermes Python environment. Missing skills, referenced files, required APIs, or
behavioral proof leaves the browser stage incomplete even when `hermes` is
present. See [Runtime dependencies](dependencies.md) for the exact inventory
and smoke checks, including the required Poppler `pdftotext` and `pdftoppm`
commands.

Use the operator's chosen vault or secret injection system. On a headless VPS, preserve an existing 1Password Connect configuration or use a least-privilege service account with its token hidden and local to the Chiron process. Connect environment takes precedence; never clear it or rewrite an existing Hermes environment globally. Validate Connect with scoped sentinel `op read`/`op run` calls and a secret-free success signal; do not use `op user get --me` for Connect. For a service account, verify `op user get --me` before scoped `op read`/`op run`. Manual CLI sessions are an interactive fallback and expire after 30 minutes of inactivity. The [manual-session](https://www.1password.dev/cli/sign-in-manually) and [service-account](https://www.1password.dev/service-accounts/use-with-1password-cli) guides are authoritative. Provider and Photon login require owner consent/device approval. Test vault usability with a disposable sentinel and prove retrieval, process-local injection, controlled restart behavior, and log redaction. If the onboarding identity is read-only, the owner may create and remove the sentinel in the normal vault UI; never expand write scope just for setup.

## Isolated Chromium and phone takeover

Give Chiron its own Chromium `user-data-dir` and loopback CDP port. Never attach it to a shared personal profile. Prove CDP by filling a harmless page, disconnecting, reconnecting, and observing retained state.

Keep VNC and noVNC private. Publish noVNC only through `cloudflared` with HTTPS and an owner-only access policy. The decisive proof is an unauthenticated denial followed by authenticated control from a phone-sized browser of the same retained Chromium page. Do not assume the VPS desktop has biometric hardware; complete passkey/MFA/device approval on the owner's capable phone or client.

## Photon/iMessage

Photon is optional and uses a managed persistent connection rather than a public webhook. The owner supplies their phone number and approves the Photon device login. Preserve an existing project, prefer pairing or an allowlist, and prove owner-authorized send/receive, retained conversation identity, and reconnect after restart. Photon is not a job-discovery/import path; do not use messaging access to scrape email or contact employers.

## Local verification

```bash
# Run your Codex installation's skill quick-validator against skills/chiron-setup.
python3 -m unittest discover -s test/onboarding -v
```

The setup structure was inspired by Cyrus's agent-guided onboarding at pinned commit [`035cfccc4856f2e853725779923e874d3af9cad8`](https://github.com/cyrusagents/cyrus/tree/035cfccc4856f2e853725779923e874d3af9cad8), licensed Apache-2.0. Chiron's implementation is newly written; the precise source and inspected files are recorded in the skill's `references/upstream.md`.
