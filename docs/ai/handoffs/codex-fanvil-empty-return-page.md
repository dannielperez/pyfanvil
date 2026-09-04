# HANDOFF: codex/fanvil-empty-return-page

- Changed: `src/pyfanvil/webconfig.py` now replays the legacy Rapid Logic login
  form's advertised `ReturnPage`, defaulting to empty when the field has no
  value, as on Guardia 11. It also recognizes the authenticated Rapid Logic
  frameset returned by the factory-default phone instead of requiring one of
  two firmware-specific child-page names. `identify()` now reads the labeled
  model value so slash-separated X-series identifiers are preserved.
- Changed: `tests/test_webconfig.py` covers both the live empty-field behavior
  and a firmware variant that advertises a non-empty return page, the alternate
  authenticated frameset, and the `X3S/X3SP` model format.
- Evidence: Guardia 11 exposes an empty `ReturnPage`; the factory-default phone
  exposes `/`. Direct pyfanvil diagnostics showed the latter returned a 6,605
  byte authenticated frameset after POST, but the old marker check rejected it.
- Validation: targeted test failed before the implementation and passed after;
  full suite passed (`55 passed`); `ruff check .` passed; formatting was applied
  to the touched module.
- Live validation: browser login with the owner-supplied credential succeeded;
  direct pyfanvil login/logout, `identify()`, and `read_sip()` succeeded against
  the factory-default phone. A no-change `set_sip_server()` exercised the
  `set_fields()` form replay and the before/after SIP snapshots were identical.
  No credential, network, or SIP value was printed or persisted.
- Review fanout: SDK-boundary reviewer `OK`; stability reviewer `OK`; migration
  review not applicable because the change has no model, migration, or backfill.
- Risk: low and limited to legacy form capability detection plus model parsing.
  The embedded-nonce path is unchanged, and legacy variants keep their
  form-advertised value. Vendor I/O remains timeout-bounded and no retries or
  app-layer behavior changed.
- Blocker: live confirmation requires owner merge, a UniqueOS pin update, and a
  UAT shipment before rerunning the connection test.
- Next step: open a draft pyfanvil PR; after owner merge, pin it in a separate
  UniqueOS draft PR and repeat the owner-approved UAT test.
