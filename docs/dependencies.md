# Runtime dependencies

ChironJP keeps dependency inventory separate from behavioral proof. The
read-only checker records installed versions and verifies the required import,
executable, CLI-help, and noVNC asset surface. It does not open a Hermes profile,
read a configuration or credential, launch a browser, compile a resume, contact
an employer, or prove the authenticated handoff path.

## Tested defaults and required surfaces

Versions in this table are reproducible, tested installation defaults and
provenance anchors. They are not a reason to reject an otherwise compatible
existing runtime. A different version is reported as `untested`; it blocks
readiness only when a required command or API is missing or a known
incompatibility is identified.

| Component | Tested default | Public provenance |
| --- | --- | --- |
| Python | 3.11 or newer | [Python](https://www.python.org/downloads/) |
| Browser Harness | 0.1.9 | [PyPI release](https://pypi.org/project/browser-harness/0.1.9/), tag `v0.1.9`, commit `41108b8676d4bdb58b26ab3b079c0b7b0f8f3926` |
| Browser Use | 0.13.8 | [PyPI release](https://pypi.org/project/browser-use/0.13.8/), tag `0.13.8`, commit `eb4126921bea3373f91afc49fb4b59d6eda7fed6` |
| websockets | 15.0.1 | [PyPI release](https://pypi.org/project/websockets/15.0.1/), tag `15.0.1`, commit `37c9bc0781f0cc5af7c729947ef1833c1e12b70d` |
| bcrypt | 5.0.0 | [PyPI release](https://pypi.org/project/bcrypt/5.0.0/) |
| websockify | 0.13.0 | [PyPI release](https://pypi.org/project/websockify/0.13.0/) |
| Hermes Agent | 0.20.0, release 2026.8.3 | [signed release](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.3), tag commit `3c27eb6234bf91b8ceee9e9071591b31e9b148cb` |
| Tectonic | 0.16.9 | [upstream tag](https://github.com/tectonic-typesetting/tectonic/tree/tectonic%400.16.9), commit `66b6654103501b0a4a6926a7c450264be59cf927` |
| Poppler tools | 26.05.0 | [upstream project](https://poppler.freedesktop.org/), tag `poppler-26.05.0`, commit `b0091f08803ffe7784e365db45abd003159bf45d` |

The Hermes check requires the stock invocation surface used by the real
runtime: `--skills`, `--usage-file`, `--reasoning`, `--oneshot`, and the
`--profile` selector. Chiron supplies the Tailor or browser workspace as the
subprocess working directory rather than relying on a non-stock directory
flag. The checker tests the selector against an empty temporary
Hermes home; it never enumerates or opens existing profiles.

Chromium, Xvfb, x11vnc, websockify, and noVNC are distribution-managed runtime
components. Their security revisions vary by supported operating system, so the
checker records an observed version where the tool exposes one and otherwise
reports availability. Use maintained distribution packages. Their upstreams
are [Chromium](https://chromium.googlesource.com/chromium/src/),
[X.Org Server](https://gitlab.freedesktop.org/xorg/xserver),
[x11vnc](https://github.com/LibVNC/x11vnc),
[websockify](https://github.com/novnc/websockify), and
[noVNC](https://github.com/novnc/noVNC).

## Fresh isolated installation

Use installation and state roots owned only by this deployment. The following
paths are examples; do not substitute an existing shared Hermes home or browser
profile.

Install maintained display/browser packages through the host distribution. On
a Debian-family host the package names are typically:

```bash
sudo apt-get install chromium xvfb x11vnc websockify novnc
```

Create a dedicated Python environment and retain the tested browser and Review
defaults:

```bash
uv venv --python 3.11 /srv/chironjp/runtime/browser-venv
uv pip install --python /srv/chironjp/runtime/browser-venv/bin/python \
  'browser-harness==0.1.9' 'browser-use==0.13.8' 'websockets==15.0.1' \
  'bcrypt==5.0.0' 'websockify==0.13.0'
```

For a reproducible new Hermes install, download the installer from the immutable
release commit and direct both the program and data to new Chiron-owned roots:

```bash
curl -fsSLo /srv/chironjp/runtime/hermes-install.sh \
  https://raw.githubusercontent.com/NousResearch/hermes-agent/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/scripts/install.sh
bash /srv/chironjp/runtime/hermes-install.sh \
  --branch v2026.8.3 \
  --commit 3c27eb6234bf91b8ceee9e9071591b31e9b148cb \
  --dir /srv/chironjp/runtime/hermes-agent \
  --hermes-home /srv/chironjp/state/hermes \
  --skip-setup --non-interactive
```

Tectonic 0.16.9 is the tested rendering default. Install it from the immutable
source revision or the corresponding upstream release asset. A source
installation can use:

```bash
cargo install --locked --root /srv/chironjp/runtime/tectonic \
  --git https://github.com/tectonic-typesetting/tectonic.git \
  --rev 66b6654103501b0a4a6926a7c450264be59cf927 tectonic
```

Prefer the maintained distribution `poppler-utils` package; it provides the
actual `pdftotext` geometry reader and `pdftoppm` PNG renderer used here:

```bash
sudo apt-get install poppler-utils
```

Poppler 26.05.0 is the tested default, not a mandatory distribution version.
The checker labels another version `untested` when the required
`pdftotext -bbox-layout` and `pdftoppm -png -r` command surface is present.

These commands install software only. Provider sign-in, an owner-approved
canonical profile, Cloudflare/noVNC access, and optional Photon/iMessage setup
are separate consented stages. Never place a token on the command line.

## Existing Hermes installation

Do not update, replace, inspect, or change an existing Hermes installation just
to run this check. Point `--hermes` at its executable. If the version and flags
match, leave its default profile and environment untouched; later runtime calls
must select Chiron's isolated named profile explicitly with `--profile`.

Version difference alone does not require an update or sidecar. When the checker
reports `untested` but all required flags work, keep the existing installation
and proceed to isolated behavioral proof. Only a missing/incompatible required
surface calls for an owner-approved upgrade or a separate installation under a
new Chiron-owned program root and home. Do not use `hermes profile use` to
change the sticky default, and do not clear the shared environment globally.
Process-local configuration is the safe boundary.

## Inventory command

Run the checker with explicit paths when the tools are not on the service
account's `PATH`:

```bash
python3 scripts/check_runtime_dependencies.py \
  --browser-python /srv/chironjp/runtime/browser-venv/bin/python \
  --browser-use /srv/chironjp/runtime/browser-venv/bin/browser-use \
  --hermes /srv/chironjp/runtime/hermes-agent/venv/bin/hermes \
  --tectonic /srv/chironjp/runtime/tectonic/bin/tectonic \
  --pdftotext /usr/bin/pdftotext \
  --pdftoppm /usr/bin/pdftoppm
```

Add `--json` for machine-readable output. The process exits zero when every
required API, flag, executable command, and asset is present. Tested-default
versions report `ok`; other versions report the non-blocking `untested` status
when their required surface passes. Output deliberately omits
resolved paths and command output so host layout and accidental environment
content cannot become release evidence.

The checker labels every result `live_proof: false`. Its focused smoke imports
the required browser, password-hashing, and WebSocket proxy APIs, checks the
shipped noVNC entry point and `core/rfb.js`, and checks CLI help without opening shared state. After
a ready inventory, run the repository's isolated resume, browser, handoff,
Hermes, and authenticated noVNC proofs. A package version or successful
`--help` is never evidence that a form was prepared, a message was delivered,
or an application was submitted.
