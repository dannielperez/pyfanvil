# pyfanvil

Small Python helpers for Fanvil IP phones and intercoms.

Current scope:

- Render credential-safe, operator-confirmed Fanvil RTSP stream addresses.
- Build Fanvil XMLService payloads for static IPv4 network changes.
- Apply XMLService requests with basic or digest authentication.
- Plan host-octet-preserving subnet migrations.
- Keep disruptive IP changes explicit and easy to dry-run.

This package is intentionally generic. Site-specific inventory and migration ordering should live outside the package.

Fanvil video-capable firmware displays the effective main/sub-stream URLs in
its camera settings. Pass that reviewed path explicitly; the library does not
guess camera capability or a stream path from a model name. Never persist or
log the rendered URL because it may contain credentials.

## Install

```bash
pip install -e ".[dev]"
```

## Quick example

```python
from pyfanvil import FanvilClient, plan_static_network

config = plan_static_network(
    "192.168.110.252",
    "192.168.110.0/24",
    "10.0.0.0/24",
)
client = FanvilClient("192.168.110.252", username="admin", password="...")
print(client.build_static_network_xml(config))     # dry-run
# response = client.apply_static_network(config)   # disruptive
```

## Testing

```bash
pytest -q
```

## License

[MIT](LICENSE).
