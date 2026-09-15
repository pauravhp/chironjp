# Public-release proof matrix

The public preview is not considered deployment-proven until the evidence below
is captured from a release candidate. Rows remain **Not run** unless their
status records a narrower, explicitly labelled local proof. Update a row only
after observing the named artifact; link redacted evidence without publishing
credentials, candidate data, cookies, private host addresses, or browser state.

Mock pages, intercepted requests, dry runs, and synthetic delivery are useful
tests, but they must be labelled as such. They never prove that an application
was delivered to an employer. The only permitted real final submission is a
human action after review.

The boundary follows behavior, not a generic label. An “Apply” link that only
opens the form is not a final action; a control that actually transmits the
application is human-only regardless of what the site calls it.

## Historical operational aggregate

As of 2026-09-15 06:18 UTC, an audited aggregate snapshot contained 23
canonical recorded submissions from non-public, multi-version operation across
10 ATS families. Fifteen were backed by rendered employer-confirmation
evidence: 11 historical final-action confirmations, two human-desktop
confirmations, and two historical guard-violation submissions. The other eight
were owner-reported submission records. These records span earlier versions and
submission behaviors. The Xsolla accepted offer described in the README belongs
to an earlier non-public version and is separate from this aggregate.

This is a count of canonical operational records, not raw application evidence.
No raw IDs or personal details are published here. It provides no conversion
rate, public-build benchmark, or safety guarantee, and it does not prove that
the current release reproduces those historical outcomes.

| Proof | Isolated setup | Required exercise | Passing evidence | Status |
| --- | --- | --- | --- | --- |
| Disposable VPS-equivalent, fresh home | Clean supported Linux VM/container; new unprivileged user and empty home; no credentials | Clone the release candidate, follow only the published README, install, start, stop, then uninstall/recreate | Full redacted command transcript and versions; health/output expected by the README; inventory showing writes remain in documented checkout/runtime paths | Not run |
| Existing-Hermes non-clobber | Disposable host with a functioning, non-production Hermes installation and canary state; snapshot its owned units, containers, ports, paths, hashes, and health without opening secrets | Install/start/use/stop Chiron with its documented defaults, then remove only Chiron-owned state | Before/after inventory has no Hermes delta; Hermes health and canary are unchanged; no shared unit/container/volume/user/port/config name | Not run |
| Fictional profile and resume render | Fresh runtime state containing only a clearly fictional profile and resume bank | Select the example role/profile and render each documented output format | Human-reviewed render has correct example identity, role choice, page layout, links, and no host path, secret, hidden real identity, or overflow | Not run |
| Source ingestion to review/demo | Controlled public source fixture plus a separately labelled live-source check if authorized | Ingest, normalize canonical employer/application identity, deduplicate, rank/select, and open the retained item in the review UI | Trace connects source identity to normalized record and review view; rerun is idempotent; no submission/network delivery occurs | Not run |
| Authenticated phone-sized noVNC and input | Non-production host; TLS/authenticated gateway; browser/VNC/debug ports not publicly exposed | Sign in from a phone-sized viewport, reach the retained employer form, scroll, focus/type/edit an innocuous fictional field, and return control | Screen recording or timestamped screenshots show auth challenge, mobile viewport, successful two-way input, retained form state, and human-only final control; redact addresses and tokens | Local synthetic HTTPS/UI PASS (390-by-844 rendered sign-in, shipped noVNC, pointer/scroll, visible local typed/pasted text, explicit Insert, guarded Return/reconnect, retained fictional field); external TLS/access edge and employer page not run |
| Hermes/Photon iMessage, credentials permitting | Operator-authorized Photon credential and an owner-controlled sender/recipient in a disposable Hermes environment | Send one clearly labelled test message with owner authorization, receive the controlled reply through Hermes/Photon, restart the connection, verify reconnect and retained message identity, then withhold or revoke the credential and repeat the failure path | Redacted trace shows real provider connection, outbound and inbound message identities/timestamps, restart/reconnect continuity, and safe withheld/revoked-credential handling; no credential appears in logs or process arguments; mocks are labelled and do not pass this row | Not run / conditional |
| Human final-action invariant | Synthetic employer fixture first; a real employer page only for an owner-authorized application | Let automation prepare the final review state and attempt every supported autonomous transition, including intermediate links that merely open the form | Automated path cannot activate Submit, Send, Confirm, or any equivalent control whose observed effect is final delivery; event evidence records handoff; for any real delivery, separate owner evidence records the human action | Not run |
| Public-tree audit and license review | Exact tagged worktree and generated release archive | Run tests and `node scripts/release-audit.mjs .`; inspect root/upstream notices, source revision, asset licenses, generated artifacts, history, and archive contents | Clean audit output plus human sign-off listing upstream project, immutable source revision, applicable license text/notices, changed-file provenance, and archive hash | Not run |

## Evidence rules

- Record the release commit, OS image, runtime versions, commands, and UTC time.
- Prefer an ephemeral host and fictional reserved data. Redact values rather
  than cropping away the surrounding state needed to understand the result.
- Keep raw proof artifacts private until a second person checks them for PII,
  secrets, machine addresses, and browser/session identifiers.
- Treat a skipped step, unavailable credential, edited transcript, or result
  from another commit as a gap. State it plainly; do not infer a pass.
- Record failures as evidence too, including cleanup state and whether any
  external request could have been sent.
