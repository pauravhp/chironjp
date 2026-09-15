# Isolated browser and authenticated takeover

## Profile and CDP

Allocate a Chiron-only Chromium user-data directory in the private runtime workspace. Reject a path already used by the owner's everyday browser or another agent. Bind the CDP listener to loopback and select an unused port. Do not expose a remote-debugging port publicly.

Launch flags depend on the installed Chromium build, but the effective behavior must include:

- a distinct `--user-data-dir`;
- a loopback remote-debugging address and dedicated port;
- a visible desktop session when forms, CAPTCHA, file uploads, or owner takeover require it.

Verify by requesting the loopback CDP version endpoint, attaching a client, navigating a harmless page, changing a field, disconnecting, reconnecting, and observing the retained state. A successful TCP connect or Chromium binary version is not enough.

Do not reuse another process's profile after a lock error. Do not weaken Chromium sandboxing as a default workaround. Never capture passwords, MFA codes, payment details, or unrelated tabs in screenshots/logs.

## noVNC and Cloudflare

Keep VNC and websockify/noVNC listeners private (loopback or a private container network). Put the public route behind `cloudflared`, HTTPS, and an access policy such as Cloudflare Access. Require an identity the owner controls and short sessions appropriate to the threat model. Do not rely on an obscure URL or noVNC's URL password parameter.

Agent-prepared work may include installing packages, writing a scoped service definition, opening the Access dashboard, and drafting policy fields. The owner must approve domain/DNS changes, account consent, identity-provider login, and any billable plan.

Connection proof is behavioral:

1. The private VNC/noVNC path renders the isolated Chromium desktop.
2. The public HTTPS URL denies an unauthenticated browser.
3. After owner authentication, a **phone-sized browser** can take control, type into the retained draft, and hand control back without losing the page.
4. CDP continues to address that same isolated profile after takeover.

Do not assume the VPS desktop can perform Touch ID, Face ID, Windows Hello, or passkey biometrics. If an identity provider demands an unavailable VPS biometric flow, authenticate on the owner's phone/client or choose a supported owner-approved factor. Use a guided manual fallback only when automation cannot safely cross account consent, device login, CAPTCHA, or MFA.

## Application boundary

The agent can prepare a real authorized employer form, including ordinary Apply/navigation controls, profile fields, resume upload, and draft free-text answers. It must pause on ambiguity and stop with the form open before the evidenced final submission control—usually Submit, Send, or Confirm, and Apply only when that control itself transmits the application. The owner reviews the actual employer page through noVNC and performs that final action.
