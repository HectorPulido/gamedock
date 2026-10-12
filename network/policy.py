"""Validated per-game egress policy and firewall rules shared by portal/gateway."""
import ipaddress

BLOCKED = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "224.0.0.0/4",
    "240.0.0.0/4",
)
DNS = ("9.9.9.9", "149.112.112.112")


def validate_policy(value=None, internet=False):
    if value is None:
        value = {"mode": "internet" if internet else "offline"}
    if not isinstance(value, dict) or set(value) - {"mode", "allow", "deny"}:
        raise ValueError("Invalid network policy")
    mode = value.get("mode", "offline")
    if mode not in ("offline", "internet", "allowlist"):
        raise ValueError("Unknown network mode")
    allow, deny = value.get("allow", []), value.get("deny", [])
    if (
        not isinstance(allow, list)
        or len(allow) > 64
        or not isinstance(deny, list)
        or len(deny) > 64
    ):
        raise ValueError("Network policy allows at most 64 rules per list")
    result = []
    for rule in allow:
        if not isinstance(rule, dict) or set(rule) != {"cidr", "port", "protocol"}:
            raise ValueError("Network exceptions require cidr, port and protocol")
        try:
            address = ipaddress.ip_network(rule["cidr"], strict=True)
        except (ValueError, TypeError):
            raise ValueError("Network exceptions require an IPv4 address or CIDR")
        if (
            address.version != 4
            or address.prefixlen == 0
            or rule["protocol"] not in ("tcp", "udp")
            or type(rule["port"]) is not int
            or not 1 <= rule["port"] <= 65535
        ):
            raise ValueError("Invalid IPv4 network exception, protocol or port")
        result.append({**rule, "cidr": str(address)})
    denied = []
    for cidr in deny:
        try:
            address = ipaddress.ip_network(cidr, strict=True)
        except (ValueError, TypeError):
            raise ValueError("Blocked destinations require IPv4 CIDRs")
        if address.version != 4:
            raise ValueError("Blocked destinations require IPv4 CIDRs")
        denied.append(str(address))
    return {"mode": mode, "allow": result, "deny": denied}


def output_rules(policy, protected=()):
    """OUTPUT only; no user-controlled shell fragments. Denies override exceptions."""
    rules = (
        [["-d", "127.0.0.11/32", "-j", "REJECT"]] if policy["mode"] == "offline" else []
    ) + [
        ["-o", "lo", "-j", "ACCEPT"],
        ["-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"],
    ]
    for cidr in [*protected, *policy["deny"]]:
        rules.append(["-d", cidr, "-j", "REJECT"])
    if policy["mode"] != "offline":
        for ip in DNS:
            for protocol in ("udp", "tcp"):
                rules.append(
                    ["-d", ip, "-p", protocol, "--dport", "53", "-j", "ACCEPT"]
                )
        for rule in policy["allow"]:
            rules.append(
                [
                    "-d",
                    rule["cidr"],
                    "-p",
                    rule["protocol"],
                    "--dport",
                    str(rule["port"]),
                    "-j",
                    "ACCEPT",
                ]
            )
        if policy["mode"] == "internet":
            for cidr in BLOCKED:
                rules.append(["-d", cidr, "-j", "REJECT"])
            rules.append(["-j", "ACCEPT"])
    return rules
