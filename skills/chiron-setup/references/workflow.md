# Setup and recovery workflow

Use this workflow for both a clean machine and a machine where Hermes is already running. Record no secrets in the ledger. A stage is complete only after its proof succeeds; on rerun, recheck cheap live proofs and resume at the first incomplete or stale stage.

## 1. Establish scope and mode

Ask for or confirm:

- an absolute Chiron runtime workspace, separate from this public repository;
- an absolute Hermes home, if one already exists;
- whether the owner wants Photon/iMessage and remote noVNC;
- which vault or secret-injection mechanism the operator will use.

Inspect without mutation: the configured Hermes command/service, process status, local health or gateway response, and a harmless authenticated agent interaction if available. Classify:

- **Fresh/no Hermes:** no configured service responds and the owner confirms a new install is wanted.
- **Existing/running Hermes:** a configured service responds and a harmless request completes. Preserve its home, service unit, provider config, skills, and browser profiles.
- **Existing/incomplete:** artifacts exist but the behavioral check fails. Diagnose the smallest missing stage. Do not initialize over it.

Binary presence, a directory, or a running PID alone does not establish a working runtime.

## 2. Initialize Chiron state

Run `setup_state.py init`. It copies only missing blank profile/worker templates, the canonical blank resume bank, and the value-free LaTeX template into actual Chiron paths, then creates `.chiron-setup/state.json` atomically. Existing files are reported as `kept`; they are never overwritten. The renderer fills identity/contact/education from the explicitly bound canonical profile. `status` shows stage state without reading values from secret stores.

For recovery, check evidence from the ledger against current behavior. If a completed stage no longer passes, mark it stale and repair only that stage. Never delete the ledger to force a clean run.

## 3. Canonical data

Create one owner-controlled canonical profile override and resume bank. Normalize owner-confirmed resume/interview evidence into the bank's provenance fields; do not invent a second bank schema. Build a Tailor manifest from canonical IDs and render it through the repository's `chironjp.resume` contract.

Proof: bank and manifest validate; the LaTeX build is one page with no overflow, clipping, or text intersections; the exact generated PNG passes vision inspection bound to the selection and preview hashes; the owner confirms identity and claims. Do not mark complete from file existence.

## 3b. Prove the real Chiron path

Setup is not complete because templates or ledger files exist. In an isolated workspace, drive a fictional or explicitly authorized source record through the actual public path: normalized source → SQLite ingress/deduplication → package and Tailor request → validated LaTeX/PDF and exact-PNG inspection → Hermes with its isolated Chromium target → retained Review → authenticated phone noVNC takeover. The final submission control stays untouched. Record only artifact hashes and behavioral outcomes, never personal contents or credentials.

## 4. Hermes and provider auth

For a fresh setup, use the current official Hermes installation path selected by the owner. Show the source and exact command before executing any network-fetched installer. For an existing runtime, use its installed CLI and configuration mechanism; do not reinstall just to normalize layout.

Create new, dedicated Hermes profiles for Chiron even when Hermes already exists; never install Chiron skills into `default` or another shared profile. Select the owner-approved Hermes root explicitly for every command, check its profile list first, and choose unused lowercase names. The stock profile-scoped command form is `hermes -p PROFILE COMMAND`. For example, after the owner approves the root and profile names:

```bash
CHIRONJP_HERMES_ROOT=/srv/chiron-runtime/hermes
HERMES_HOME="$CHIRONJP_HERMES_ROOT" hermes profile list
HERMES_HOME="$CHIRONJP_HERMES_ROOT" hermes profile create chirontailor --no-skills
HERMES_HOME="$CHIRONJP_HERMES_ROOT" hermes profile create chironbrowsera --no-skills

export CHIRONJP_RELEASE_REVISION='replace-with-an-immutable-public-commit'
HERMES_HOME="$CHIRONJP_HERMES_ROOT" hermes -p chirontailor skills install \
  "https://raw.githubusercontent.com/pauravhp/chironjp/${CHIRONJP_RELEASE_REVISION}/worker/skills/chiron-resume-tailor/SKILL.md" --yes
HERMES_HOME="$CHIRONJP_HERMES_ROOT" hermes -p chironbrowsera skills install \
  "https://raw.githubusercontent.com/pauravhp/chironjp/${CHIRONJP_RELEASE_REVISION}/worker/skills/chiron-application-executor/SKILL.md" --yes
```

Do not substitute a branch name for the immutable revision. Direct `SKILL.md` URL installation is a stock Hermes path and also retrieves explicitly referenced support files. Do not use `--force` to bypass a scan result. On a rerun, do not recreate or overwrite a profile: prove its identity, inspect `hermes -p chirontailor skills list --enabled-only` and `hermes -p chironbrowsera skills list --enabled-only`, then install only a missing skill into its intended dedicated profile. Use `--skills chiron-resume-tailor` only on Tailor runs and `--skills chiron-application-executor` only on browser runs; `--skills` preloads an installed skill and is not an installer.

For a fresh isolated browser runtime, install the tested defaults
`browser-harness==0.1.9` and `browser-use==0.13.8` with the owner's selected
locked Python tooling. For an existing runtime, inspect the installed versions
and run the required helper/API and browser smoke checks: another version is
untested, not automatically incompatible. Do not mutate a shared Hermes Python
environment or require a sidecar upgrade solely to match a version. A missing
local skill, referenced file, required API, or behavioral proof keeps the
Hermes/browser stage **incomplete**; command availability alone is not proof.
Use the repository dependency checker for this inventory, including the
renderer-required `pdftotext` and `pdftoppm` surfaces.

Populate the actual `config/chiron-workers.json` registry with generic, Chiron-owned absolute paths: `runtime_root`, `state_root`, a database inside the runtime root, and `hermes_profile_root` set to the selected Hermes root's direct `profiles` directory. Each of at least two uniquely identified worker records needs a unique Hermes profile, Chromium profile under the runtime root, workspace under the state root, CDP/VNC/noVNC ports, and X display. The runtime passes the exact named profile directory as process-local `HERMES_HOME`; it never relies on a sticky default. Never point browser fields at an existing shared browser directory. Disable unused workers instead of deleting the non-singleton shape. The Tailor has a separate Hermes profile and workspace and no browser profile.

Configure role targets only after checking the installed Hermes/provider documentation and model availability:

- browser/application preparation: provider `nous`, model `z-ai/glm-5.3-flash`, high reasoning;
- Tailor/resume selection: provider `openai-codex`, model `gpt-5.6-terra`, high reasoning.

Names and availability can change. Store verified identifiers in private runtime configuration, while leaving repository templates blank. Do not claim a Codex-only runtime path is proven.

Provider login, subscription selection, consent, MFA, and device authorization belong to the owner. The agent may open the correct page, explain requested scopes, and fill non-secret fields. Use device-code or stdin/hidden prompt flows where supported. Never paste a token into chat or pass it on a command line.

Proof: a minimal authenticated model request completes for each configured role and the response identifies/telemeters the expected provider/model where supported. Redact bodies that could contain user data.

## 5. Operator vault usability

Choose the owner's existing vault when possible. Do not create a parallel secrets file merely because it is easier for the agent. Establish:

- the service account/session can retrieve only the intended entries;
- Hermes can receive required values at process start without printing them;
- restart preserves access under the same least-privilege identity;
- logs, shell history, process arguments, state JSON, and generated files contain no secret.

Use a disposable sentinel credential for the retrieval/injection test. If the onboarding identity is read-only, the owner creates and later deletes the sentinel in the normal vault UI; do not expand write scope for setup. Compare only a hash or fixed success signal. Never inspect or enumerate unrelated vault entries.

Proof: retrieve/inject/restart behavior succeeds with the sentinel, and a redaction/log check is clean. Sentinel creation is not part of this identity's proof when the owner supplies it.

### Headless/VPS 1Password branch

For an existing 1Password Connect deployment, preserve its scoped `OP_CONNECT_HOST` and `OP_CONNECT_TOKEN` injection; Connect variables take precedence over `OP_SERVICE_ACCOUNT_TOKEN`. Never clear them, rewrite the existing Hermes environment globally, or mix authentication modes inside one process. Validate Connect by using scoped `op read` and `op run` against the exact sentinel and observing only a secret-free success signal. Do not use `op user get --me` for Connect.

Otherwise, prefer a least-privilege 1Password service account for a headless service. The owner creates it and enters `OP_SERVICE_ACCOUNT_TOKEN` through a hidden, Chiron-process-local service credential or secret environment input—not chat, shell history, a command argument, or a shared/global Hermes file. Verify with `op user get --me`; use `op read` for exact item references or `op run` to inject only into the Chiron child process. [1Password's service-account CLI guide](https://www.1password.dev/service-accounts/use-with-1password-cli) documents those commands and Connect precedence.

Interactive manual CLI sign-in is a guided fallback, not an unattended-service credential. The owner performs the prompt; its session expires after 30 minutes of inactivity. See [1Password's manual sign-in guide](https://www.1password.dev/cli/sign-in-manually). On a VPS without a suitable interactive flow, stop for the owner to provision Connect or a scoped service account.

For either branch, retrieve the disposable sentinel without printing, compare a digest or fixed success signal, run a harmless Chiron subprocess through the same injection path, restart that scoped process, and repeat the check. An owner who supplied the sentinel removes it through the normal vault UI afterward. Check that logs, ledger, process arguments, and generated files contain neither value nor token.

## 6. Browser and real employer-form preparation

Follow [browser-remote-access.md](browser-remote-access.md). The behavioral proof must exercise CDP attachment, navigation, field filling on a harmless local fixture or authorized employer draft, persistence across reconnect, and owner takeover. File existence and open ports are insufficient.

The operational browser agent may navigate and prepare an actual selected employer form using owner-confirmed canonical answers, including an authorized name/signature value and supplied demographic preferences. Sensitive facts stay unset until the owner supplies or authorizes them; never infer. Human action is required only where the rendered flow actually requires human authentication/CAPTCHA/consent and for the evidenced final submission control.

## 7. Photon/iMessage (optional)

Follow [photon.md](photon.md). Proof requires a permitted inbound/outbound owner conversation, stable retained message identity, and restart/reconnect. Do not treat a stored token or installed sidecar as success, and do not route job discovery/import through Photon.

## 8. Service and restart recovery

Use the owner's service manager. Pin working directories and private runtime paths explicitly. Start only the Chiron/Hermes units in scope. After a controlled restart, verify:

- Hermes answers a harmless request;
- provider auth still works;
- the isolated browser reconnects to the same retained draft;
- noVNC remains HTTPS/authenticated and supports phone takeover;
- selected messaging channels reconnect.

Record concise, non-secret evidence with `setup_state.py mark`. If one stage needs account consent, device login, billing selection, new public exposure, or an owner answer, park that stage with the exact pending action and continue any independent owner-authorized setup stages. Existing scope covers configuring the owner-selected Cloudflare and Photon paths; it does not waive their actual consent/device prompts.
