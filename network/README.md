# Session firewall

Build once per Docker host: `docker build -t gamedock-network:local network`.
The local setup and QA scripts build this image automatically. All new sessions
require it, including offline sessions; there is no unfiltered fallback.

Configure each game's **Session network** in Administration → Games. The JSON
representation is:

```json
{
  "network_policy": {
    "mode": "internet",
    "allow": [{"cidr": "192.168.0.7/32", "port": 5555, "protocol": "tcp"}],
    "deny": ["203.0.113.10/32"]
  }
}
```

Modes: `offline`, `internet`, `allowlist`. Online modes permit DNS to Quad9 over
TCP/UDP 53. Offline mode also blocks Docker's embedded DNS destination. Exceptions
use IPv4 addresses/CIDRs and individual TCP/UDP ports, rather than DNS names that
could change or resolve to local addresses. Offline mode ignores exceptions.
User-provided denies override exceptions. Portal and bridge gateway addresses
are always protected, even from explicit exceptions. IPv6 egress is denied.
Loopback inside the session remains available to the game's local components.

The portal starts an immutable firewall container with only NET_ADMIN, no Docker
socket, a 64 MiB memory limit and a private temporary filesystem. It waits until
both IPv4 and IPv6 firewall setup succeeds, then starts the game sharing that
network namespace. The game does not receive NET_ADMIN. Incoming connections are
restricted to the portal's IP and TCP 6084/6085; established replies are permitted.
On portal recreation, its original session IP is restored so those rules remain
valid. Stopping a session removes the game before the namespace owner and network.

The public-Internet mode blocks the address ranges listed in `policy.py`.
Operators must additionally deny their host's public IPs and any LAN/VPN ranges
using globally routable addresses. Explicit local exceptions should use the
narrowest address and port needed. This does not prevent public-Internet access
in Internet mode, nor replace a VM boundary against kernel vulnerabilities.
Existing sessions keep their existing networking until stopped and relaunched.

## Validation (2026-10-12)

Real Docker/OrbStack tests passed for all three modes and an allowlist exception:

- Internet and DNS permitted only according to the selected mode.
- A reachable local HTTP canary blocked; explicitly allowed port reachable while
  a second listening port on the same address stays blocked.
- Portal blocked even with an exception covering its address/port.
- Bridge host, metadata and IPv6 probes cannot connect.
- Portal can reach the desktop port; another local container cannot, and even the
  portal cannot reach an unrelated listening port inside the game namespace.
- Portal disconnect/reconnect restores the original IP.
- Actual Xpra desktop pixels and controller requests work through the portal.
- Administrator form saves mode/exceptions/denies and fits a mobile viewport.
- Invalid policy and firewall startup failure covered by unit/API tests.

The live firewall test creates only ephemeral QA containers/networks/volumes:

```sh
docker run --rm -v "$PWD:/app:ro" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e PYTHONPATH=/app -e PORTAL_CONTAINER=gamedock-portal-1 \
  gamedock-portal:local python tests/network_live.py
```

The browser test additionally uses the QA browser image, `/qa.env` for credentials
and `/artifacts` for screenshots. Set `NETWORK_LAUNCH_QA=1` to also launch and stop
an actual Xpra QA desktop. Native Linux deployment should run the same tests;
this validation was performed on the local Apple Silicon/OrbStack host.
