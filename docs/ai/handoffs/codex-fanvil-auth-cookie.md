# HANDOFF: codex/fanvil-auth-cookie

- Objective: make legacy Rapid Logic Fanvil login match the device browser handshake.
- Changed: `src/pyfanvil/webconfig.py` now uses the first 16 nonce characters and sets the nonce as the session `auth` cookie before posting the digest.
- Test: `tests/test_webconfig.py` verifies nonce truncation, digest construction, and cookie correlation.
- Validation: targeted pytest passed; full pytest 52 passed; Ruff passed; `git diff --check` passed.
- Risk: low and confined to the legacy `key==nonce` path; X-series embedded-nonce login is unchanged.
- Blocker: live device validation requires the owner-approved UniqueOS pin, UAT ship, and provisioning retry.
- Next: open a draft pyfanvil PR; after owner merge, pin the merged SDK revision in a separate UniqueOS PR.
