---
name: chiron-setup
description: Set up or repair a self-hosted Chiron job-application workspace around Hermes, including candidate banks, provider auth, an isolated browser, Photon, and authenticated noVNC. Use for fresh installs and existing Hermes runtimes; do not use to submit applications or scrape mail.
---

# Chiron Setup

Prepare a recoverable Chiron workspace whose agents can tailor a resume and fill a real employer form, then leave the retained browser session for the owner to review. **The evidenced final submission control is human-only—usually Submit, Send, or Confirm, and Apply only when that control itself finally transmits the application.** Ordinary Apply navigation into a form remains available to the browser agent.

## Start safely

1. Establish the user-selected Chiron workspace and Hermes home. Treat an existing Hermes home, browser profile, vault, or service as shared state: inspect it read-only and never replace, merge, or “repair” it without naming the exact proposed change.
2. Read [references/workflow.md](references/workflow.md). Choose its fresh-Hermes or existing-Hermes path from observed runtime behavior, not binary presence alone.
3. Initialize blank config/bank files and a recovery ledger with:

   ```bash
   python3 scripts/setup_state.py init --workspace /absolute/path/to/chiron-runtime \
     --templates /absolute/path/to/chironjp/templates \
     --resume-assets /absolute/path/to/chironjp/resume
   ```

   This is non-clobbering. On a rerun, inspect `status` and skip only stages whose proof still holds. Resume the first incomplete or stale stage.
4. Populate `config/canonical-profile-overrides.json` and `resume/bank.json` with the owner. The copied value-free `resume/template.tex` receives verified identity/contact/education through the renderer's explicit profile binding. Owner-confirmed interview material enters the resume bank only through its provenance/evidence fields; do not create a parallel bank or infer personal facts. Read [references/data-and-rendering.md](references/data-and-rendering.md) when creating or validating it.
5. For runtime/provider and vault setup, follow the owner-gated steps in the workflow. Install each public Chiron worker skill only into its new/dedicated Hermes profile with the documented `hermes -p` commands; never modify a shared profile. Credentials never enter chat, command arguments, logs, screenshots, committed files, or the setup ledger.
6. For Chromium/CDP and remote takeover, read [references/browser-remote-access.md](references/browser-remote-access.md). Use an isolated Chiron profile. Never attach to or clobber a shared personal profile.
7. If the owner selects iMessage, read [references/photon.md](references/photon.md). Account creation may be prepared by the agent, but the owner performs device approval and supplies their phone number directly to the trusted setup surface.
8. Validate actual end-to-end behavior before marking a stage complete. A command existing on `PATH` is not proof that its service, auth, browser connection, tunnel, or messaging round trip works.

## Boundaries

- Prepare only applications the owner has selected or authorized. Do not scrape email, operate production mail, activate the evidenced final submission control, accept terms, or bypass CAPTCHAs/MFA.
- Keep example data isolated under `examples/fictional`; never promote it into a runtime workspace. Repository templates are deliberately blank.
- Prefer local/loopback listeners. Expose noVNC only through HTTPS plus access authentication; never publish bare VNC or an unauthenticated noVNC endpoint.
- VPS remote takeover means an authenticated phone browser controlling the isolated VPS desktop. Do not assume Touch ID, Face ID, passkeys, or other desktop biometrics are available on a VPS.
- The currently intended role split is Hermes browser work with **GLM 5.3 Flash through Nous**, and resume tailoring with **GPT-5.6 Terra High**. Confirm current provider/model identifiers and access before saving config. This is a role assignment, not evidence that a Codex-only replacement works.

## Completion

Run the setup helper, the repository resume checks, and the onboarding tests. Then report completed, skipped, and incomplete stages; the paths created; live behaviors actually proven; all owner-only actions still pending; and any provider/version assumptions.

- `python3 scripts/setup_state.py status --workspace ...`
- `python3 -m unittest discover -s test/onboarding -v`

For the setup skill's public inspiration and license boundary, see [references/upstream.md](references/upstream.md).
