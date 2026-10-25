# Native registration evidence and log export

Adds read_sip_status for a proven selected account. Parses checkbox presence separately from false; native registration code 200 alone means registered (1 is STUN wait; 100 is trying; 403 is failure). Registration never implies idle call state. Adds bounded current-log export using the advertised tools-page syslog control, with identity checks before/after, byte cap, overall async deadline, no redirects, HTML rejection and private bytes excluded from repr. Consumer owns encrypted storage/retention. No log-level or device configuration changes.

Validation: 103 offline tests pass, full Ruff lint/format pass. Read-only i16S observations verified status 200/0 and application/octet log exports around 0.5 MB. Screenshot endpoint advertised by shared markup returns 404 on these devices; not supported by this change. Native call-state polling is not established. Packet capture is not implemented: unattended activation needs a durable stop obligation and verification of existing capture ownership, including worker loss.

No new live call-state or restart authority. No firmware upgrade. TLS verification remains enabled for the async download.
