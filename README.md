# chironjp

> Early public preview. The implementation is being added now; runnable setup instructions will appear only after the public path is proven.

Chiron is a practical, agentic job-application pipeline built around a simple boundary: agents prepare real employer forms, and a human reviews and performs the final submission.

The first public sourcing path is being adapted from the MIT-licensed [career-ops](https://github.com/career-ops-hq/career-ops) project. Upstream credit and a pinned source revision will ship with that code. More personalized discovery is planned.

The public preview is being built to demonstrate an inspectable workflow:

- discover and deduplicate roles from official application identities;
- select and render a job-specific resume from a canonical, user-owned bank;
- let an isolated browser agent prepare the actual employer form;
- hand the retained form to the owner through an authenticated phone-sized desktop view;
- keep Submit, Send, and Confirm exclusively human-controlled.

Chiron targets a generic Linux VPS. Personal answers, credentials, application records, and private runtime defaults are not part of this repository. Example data will be clearly fictional and separate from runtime candidate state.

An earlier version of this project helped me apply to Xsolla. That application led to interviews, an offer, and my acceptance.

That is an owner-reported historical outcome from an earlier implementation, not a hiring guarantee or a result produced by this public build.

## License

MIT. See [LICENSE](LICENSE). Included or adapted upstream components retain their own notices and attribution.
