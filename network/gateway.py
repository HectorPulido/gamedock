"""Install the session namespace firewall before any game process can start."""
import json
import ipaddress
import os
import subprocess
import time
from policy import validate_policy, output_rules


def run(*args):
    subprocess.run(args, check=True)


policy = validate_policy(json.loads(os.environ["GAMEDOCK_NETWORK_POLICY"]))
# IPv6 must never bypass the IPv4 policy. Failure is fatal.
run("ip6tables", "-P", "INPUT", "DROP")
run("ip6tables", "-A", "INPUT", "-i", "lo", "-j", "ACCEPT")
run("ip6tables", "-P", "OUTPUT", "DROP")
run("ip6tables", "-A", "OUTPUT", "-o", "lo", "-j", "ACCEPT")
portal_ip = str(ipaddress.IPv4Address(os.environ["GAMEDOCK_NETWORK_PORTAL_IP"]))
run("iptables", "-P", "INPUT", "DROP")
run("iptables", "-A", "INPUT", "-i", "lo", "-j", "ACCEPT")
run(
    "iptables",
    "-A",
    "INPUT",
    "-m",
    "conntrack",
    "--ctstate",
    "ESTABLISHED,RELATED",
    "-j",
    "ACCEPT",
)
run(
    "iptables",
    "-A",
    "INPUT",
    "-s",
    portal_ip,
    "-p",
    "tcp",
    "-m",
    "multiport",
    "--dports",
    "6084,6085",
    "-j",
    "ACCEPT",
)
run("iptables", "-P", "OUTPUT", "DROP")
for rule in output_rules(
    policy, json.loads(os.environ.get("GAMEDOCK_NETWORK_PROTECTED", "[]"))
):
    run("iptables", "-A", "OUTPUT", *rule)
with open("/tmp/ready", "w") as ready:
    ready.write("ready")
while True:
    time.sleep(3600)
