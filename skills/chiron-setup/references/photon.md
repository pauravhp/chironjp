# Photon iMessage setup

Photon is an optional managed iMessage route for Hermes; it does not require a Mac relay or a public webhook. Recheck the installed Hermes version's official Photon help before acting because CLI and service behavior may change.

Current official Hermes guidance uses:

```bash
hermes photon setup --phone +15551234567
hermes photon status
hermes gateway start
```

The phone number shown is a placeholder, never a default. Ask the owner to type their E.164 number into the trusted setup prompt/terminal, not chat. The setup uses device approval at Photon and provisions/reuses the project and sidecar. The agent may navigate to the approval page and explain it; the owner approves the device and any terms or plan.

Preserve an existing Photon project and authorization model. Prefer DM pairing or an explicit allowlist. Never enable allow-all for convenience on an Internet-connected runtime. Do not display stored tokens, project secrets, auth files, or environment contents.

Proof requires more than `status`: verify the sidecar/gateway stays connected, have the authorized owner initiate a message when required, and observe one inbound plus one outbound round trip after a gateway restart. A message to a brand-new recipient may be rejected even when setup works, so use the owner-approved conversation and diagnose delivery semantics before rotating credentials.

Photon is the owner-authorized Hermes iMessage send/receive channel for operator interaction. Keep the message/conversation identity stable across restart and reconnect. It is not a job-discovery or source-import channel, and it does not grant permission to scrape email, contact employers, or submit applications.
