# chironjp

> Early public preview. The extracted path is runnable and inspectable, but the
> deployment proof matrix still names the checks that require your own VPS,
> provider credentials, and authenticated access edge.

Chiron is a practical, agentic job-application pipeline built around a simple boundary: agents prepare real employer forms, and a human reviews and performs the final submission.

The first public sourcing path is adapted from the MIT-licensed [career-ops](https://github.com/career-ops-hq/career-ops) project. Its pinned source revision, changed-file mapping, and license are recorded in [Third-party notices](THIRD_PARTY_NOTICES.md). More personalized discovery is planned.

The public preview is being built to demonstrate an inspectable workflow:

- discover and deduplicate roles from official application identities;
- select and render a job-specific resume from a canonical, user-owned bank;
- let an isolated browser agent prepare the actual employer form;
- hand the retained form to the owner through an authenticated phone-sized desktop view;
- optionally carry owner-authorized updates through Hermes/Photon iMessage;
- keep Submit, Send, and Confirm exclusively human-controlled.

Chiron targets a generic Linux VPS. Personal answers, credentials, application records, and private runtime defaults are not part of this repository. Included examples are clearly fictional and separate from runtime candidate state.

An earlier version of this project helped me apply to Xsolla. That application led to interviews, an offer, and my acceptance.

That is an owner-reported historical outcome from an earlier implementation, not a hiring guarantee or a result produced by this public build.

Separately, a [2026-09-15 historical aggregate](docs/proof.md#historical-operational-aggregate) records 23 canonical submissions; application preparation reached Review across 10 observed ATS families in non-public, multi-version operation. Neither figure is a public-build benchmark or conversion claim.

## Public preview

The repository now includes the Python/SQLite package and Review core, the
canonical bank-driven LaTeX renderer and exact-PNG validation contract, two
dedicated Hermes worker skills, preserved Workday/Greenhouse browser checks,
and a loopback authenticated noVNC handoff. The browser runner creates or
resumes one exact application target and retains it for owner Review; it does
not expose an autonomous final-action path.

Start with [setup](docs/setup.md), then follow the concrete
[source-to-Review runtime](docs/runtime.md). [Runtime dependencies](docs/dependencies.md)
separates tested install defaults from behavioral compatibility, and the
[proof matrix](docs/proof.md) distinguishes fixture checks from deployment or
employer evidence.

The first public source is the a16z Speedrun Talent feed adaptation credited
above. Photon/iMessage remains optional and requires the owner-authorized real
send/receive/reconnect proof described in setup; it is not a job source.

## License

MIT. See [LICENSE](LICENSE). Included or adapted upstream components retain their own notices and attribution.
