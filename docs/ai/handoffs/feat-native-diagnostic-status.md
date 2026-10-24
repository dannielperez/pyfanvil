# Native information diagnostics

Add optional hardware_version, firmware_version and raw uptime to DeviceInfo from exact information-table labels. Prefer the explicitly labeled Ethernet MAC over other interfaces; unavailable Ethernet never falls back to Wi-Fi. Preserve existing model and unlabeled legacy MAC behavior.

Validation: 87 SDK tests pass; full Ruff check and format check pass. Synthetic fixtures reproduce observed i16S information labels, with unrelated MAC and previous uptime traps. No configuration writes or additional network requests.

Limitations: English labels only for added fields; unknown firmware layouts remain None. Uptime units and the page's `(Invalid)` annotation are not interpreted. No call-state, screenshot or log capability is claimed. Next: verify supported native call-state endpoint independently.
