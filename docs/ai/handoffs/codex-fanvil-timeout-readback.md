# Fanvil ambiguous SIP-write readback

## Changed files and why

- `src/pyfanvil/webconfig.py`: treats a timeout or dropped connection after the
  SIP form POST as an ambiguous write, never replays it, and uses a configurable,
  bounded readback window to confirm all observable requested fields.
- `tests/test_webconfig.py`: covers timeout and connection-loss reconciliation,
  mismatch fail-closed behavior, password-only refusal, and timeout validation.

## Validation

- `uv run --extra dev pytest -q` — 63 passed.
- `uv run --extra dev ruff check .` — passed.
- `uv run --extra dev ruff format --check src tests` — passed.
- Repository-wide format check additionally reports the pre-existing README code
  sample spacing issue; this branch does not touch README.

## Risk and compatibility

- Deterministic HTTP errors still fail immediately.
- Ambiguous writes are accepted only after exact readback of every requested
  non-password form field; password-only writes cannot be inferred successful.
- Verification is bounded to 10 seconds by default and capped at 30 seconds.
- No mutation is retried, avoiding duplicate or oscillating device writes.

## Evidence and next step

- A UAT Fanvil SIP POST timed out, but FreePBX subsequently showed extension 118
  actively registered from the target phone while its prior extension 125 was
  unavailable. This is the firmware response-loss behavior handled here.
- After owner merge, pin this SDK revision in UniqueOS, run CI/UAT ship, then retry
  the preserved replacement job so the local 125-to-118 link can finalize.
