# Security and privacy boundary

Chiron is an early public preview for preparing job-application forms. It is
not a security boundary for untrusted code, a compliance product, or a promise
that an employer site will handle data safely. Treat the candidate profile,
resume, browser profile, cookies, credentials, form contents, downloads, and
application history as sensitive personal data.

## Trust model

The intended boundary has three parts:

1. Public source and fictional examples live in this repository.
2. Candidate data, credentials, and browser state live outside the checkout and
   are supplied at runtime by the operator.
3. Automation may navigate, draft, upload, and prepare a form. A human must
   review the actual employer page and perform the action that actually submits,
   sends, confirms, or otherwise delivers the application.

That final-action rule is a product safety boundary, not merely a user-interface
preference. A preview, dry run, intercepted request, staged page, synthetic
employer, or mocked delivery is not evidence that a real application was sent.

The system necessarily trusts its host administrator, runtime dependencies,
configured browser, remote-desktop gateway, credential provider, and the sites
the operator chooses to visit. Employer pages and job descriptions are
untrusted input: they may be inaccurate, hostile, or attempt prompt injection.
Agents must not treat page text as authority to reveal secrets, weaken the
human-submit boundary, or execute unrelated instructions.

## Secrets and personal data

- Keep real profiles, resumes, answers, cookies, exports, screenshots, logs,
  recordings, and application records out of the repository and its build
  context. Examples must use fictional names, reserved example domains, and
  reserved phone ranges.
- Inject credentials at runtime from an operator-controlled secret store. Do
  not put them in command arguments, committed environment files, generated
  configuration, URLs, logs, screenshots, or agent transcripts.
- Give each integration the narrowest practical credentials. Revoke and rotate
  them after suspected exposure; deleting a Git commit is not sufficient.
- Set restrictive permissions on runtime state and backups. Define retention
  deliberately, including for browser downloads and remote-desktop recordings.
- Do not print form values or credential-bearing browser/network traces while
  debugging. Error reporting should identify the step, not reproduce its data.

A vault reduces accidental storage and can limit access, but it does not make a
workflow lawful or safe by itself. Once a credential is released to a process
or typed into a browser, that process, browser, page, host, extensions, logs,
and screen-sharing path may expose it. Browser isolation likewise limits some
failures but is not legal immunity, consent, authorization, or a substitute for
reviewing site terms and applicable employment, privacy, and automation rules.

## Browser and remote-desktop boundary

Remote browser/debugging ports should bind only to loopback or an isolated
private network. A phone-accessible noVNC session requires authentication,
transport encryption, short-lived sessions, and an independently protected
network path; do not publish a raw VNC/noVNC or browser-debugging port to the
internet. Lock or terminate the session after handoff and verify that clipboard
and file-transfer behavior matches the operator's risk tolerance.

Button text alone does not define the boundary. An “Apply” link may only open an
application form and can be automated when that non-final behavior is observed;
an “Apply” control that actually delivers the application is human-only.
Authentication proves access to the gateway, not that the person understands
the pending form. Before the delivery action, the human should inspect the target
domain, employer and role identity, attachments, every populated answer,
required attestations, and the exact button being activated.

## Installation and coexistence

Installation must stay within documented Chiron-owned paths. It must not scan,
import, migrate, overwrite, stop, reconfigure, or reuse an existing service
merely because one is present on the host. In particular, coexistence with an
existing Hermes installation must be proven with a before/after non-clobber
test; shared names, ports, containers, systemd units, users, volumes, and
configuration paths are release blockers.

Do not run public-preview installers against a production host. Use a
disposable VPS-equivalent machine or VM and a fresh unprivileged home first.
Review commands before granting elevated privileges.

## Release guardrail

Run:

```sh
node --test test/release-audit/*.test.mjs
node scripts/release-audit.mjs .
```

The audit rejects common secrets, non-example contact data, private machine
addresses and home paths, application artifacts, logs, captures, dangerous
file types, external symlinks, private source names, and license-warning terms.
It skips version-control internals, dependency directories, and its deliberately
unsafe test fixtures. This focused scanner can miss encoded, novel, binary, or
context-dependent disclosures, so a clean result never replaces reviewing the
complete diff, generated artifacts, commit history, and release package.

## Preview limitations and reporting

This repository has not yet established a production security or availability
claim. The proof checklist in [proof.md](proof.md) records what remains to be
demonstrated. Photon and other third-party integrations are conditional on the
operator having authorized credentials and on the provider's current terms.

Report suspected vulnerabilities privately to the maintainer through an
appropriate private channel. Do not include live credentials, cookies, resumes,
or applicant data in a public issue. If no private channel is published, open a
minimal issue asking for one without disclosing the vulnerability details.
