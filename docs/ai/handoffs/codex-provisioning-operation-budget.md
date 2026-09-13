# Fanvil provisioning operation budget

## Changed files and why

- `src/pyfanvil/webconfig.py` adds `FanvilWebConfig.for_provisioning()`, a
  high-level factory that owns the bounded request, total-operation, 503 retry,
  backoff, and ambiguous-write verification policy for a SIP provisioning run.
- `tests/test_webconfig.py` verifies the profile remains bounded and preserves
  the caller's endpoint scheme.

## Validation

- `ruff format --check src tests` — passed.
- `ruff check src tests` — passed.
- `PYTHONPATH=src .../python -m pytest -q` — 65 passed.

## Risk and next step

- Existing direct constructor defaults and APIs are unchanged.
- The new profile caps a complete provisioning session at 30 seconds, each
  request at 10 seconds, 503 retries at one with a one-second backoff, and
  ambiguous-write readback at 10 seconds. Readback is clamped to the remaining
  aggregate deadline, so it cannot extend the 30-second session budget.
- After owner merge, pin the merged SDK revision in UniqueOS and use this facade
  instead of passing Fanvil transport knobs from Django application code.
