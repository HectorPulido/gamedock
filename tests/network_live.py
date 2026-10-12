"""Real firewall verification; only ephemeral QA sessions/containers are modified.
Run in portal image with Docker socket and repo mounted; PORTAL_CONTAINER must
identify the running portal. No credentials needed. Tests public Internet/DNS,
local canary services, portal, bridge host, IPv6 and reverse desktop traffic.
"""
import asyncio
import json
import os
import uuid
import aiohttp
from server.app import Docker


async def main():
    docker = Docker()
    connector = aiohttp.UnixConnector(path="/var/run/docker.sock")
    async with aiohttp.ClientSession(connector=connector) as http:
        docker.http = http

        async def execute(name, code):
            result = await docker.request(
                "POST",
                "/containers/" + name + "/exec",
                {
                    "Cmd": ["python", "-c", code],
                    "AttachStdout": True,
                    "AttachStderr": True,
                },
            )
            async with http.post(
                "http://docker/v1.45/exec/" + result["Id"] + "/start",
                json={"Detach": False, "Tty": False},
            ) as response:
                raw = await response.read()
            # Docker multiplex framing; strip frames before parsing JSON.
            output = b""
            while raw:
                length = int.from_bytes(raw[4:8], "big")
                output += raw[8 : 8 + length]
                raw = raw[8 + length :]
            state = await docker.request("GET", "/exec/" + result["Id"] + "/json")
            if state["ExitCode"] != 0:
                raise AssertionError(output.decode())
            return json.loads(output)

        probe = """import socket,json
out={}
for name,host,port in TARGETS:
 try:
  with socket.create_connection((host,port),timeout=2): pass
  out[name]=True
 except OSError: out[name]=False
try: out['dns']=bool(socket.gethostbyname('example.com'))
except OSError: out['dns']=False
print(json.dumps(out))
"""
        for case in ("offline", "internet", "allowlist", "allowlist-exception"):
            mode = case.split("-")[0]
            sid = "netqa-" + uuid.uuid4().hex[:10]
            game = "gamedock-" + sid
            canary = "gamedock-canary-" + sid
            profile = {
                "id": sid,
                "image": "gamedock-portal:local",
                "command": [
                    "python",
                    "-c",
                    'import http.server,threading;threading.Thread(target=http.server.HTTPServer(("0.0.0.0",7000),http.server.SimpleHTTPRequestHandler).serve_forever,daemon=True).start();http.server.HTTPServer(("0.0.0.0",6084),http.server.SimpleHTTPRequestHandler).serve_forever()',
                ],
                "env": {},
                "memory_mb": 128,
                "cpus": 1,
                "network_policy": {"mode": mode},
            }
            if case == "allowlist-exception":
                profile["network_policy"]["allow"] = [
                    {"cidr": cidr, "port": port, "protocol": "tcp"}
                    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
                    for port in (9000, 8080)
                ]
            try:
                await docker.start(sid, 999998, profile, "1280x720")
                net = await docker.request("GET", "/networks/gamedock-session-" + sid)
                portal_ip = next(
                    c["IPv4Address"].split("/")[0]
                    for c in net["Containers"].values()
                    if c["Name"] == docker.portal
                )
                bridge_ip = net["IPAM"]["Config"][0]["Gateway"]
                await docker.request(
                    "POST",
                    "/containers/create?name=" + canary,
                    {
                        "Image": "gamedock-portal:local",
                        "Cmd": [
                            "python",
                            "-c",
                            'import http.server,threading; threading.Thread(target=http.server.HTTPServer(("0.0.0.0",9001),http.server.SimpleHTTPRequestHandler).serve_forever,daemon=True).start();http.server.HTTPServer(("0.0.0.0",9000),http.server.SimpleHTTPRequestHandler).serve_forever()',
                        ],
                        "HostConfig": {"NetworkMode": "gamedock-session-" + sid},
                    },
                )
                await docker.request("POST", "/containers/" + canary + "/start")
                ci = await docker.request("GET", "/containers/" + canary + "/json")
                canary_ip = ci["NetworkSettings"]["Networks"][
                    "gamedock-session-" + sid
                ]["IPAddress"]
                info = await docker.inspect(sid)
                game_ip = info["NetworkSettings"]["Networks"][
                    "gamedock-session-" + sid
                ]["IPAddress"]
                await asyncio.sleep(0.5)
                targets = [
                    ("internet", "1.1.1.1", 443),
                    ("portal", portal_ip, 8080),
                    ("local", canary_ip, 9000),
                    ("other_port", canary_ip, 9001),
                    ("host", bridge_ip, 22),
                    ("metadata", "169.254.169.254", 80),
                    ("ipv6", "2606:4700:4700::1111", 443),
                ]
                result = await execute(game, "TARGETS=" + repr(targets) + "\n" + probe)
                assert result["internet"] == (mode == "internet"), (mode, result)
                assert result["local"] == (case == "allowlist-exception"), (
                    case,
                    result,
                )
                assert not any(
                    result[k]
                    for k in ("portal", "other_port", "host", "metadata", "ipv6")
                ), (case, result)
                assert result["dns"] == (mode != "offline"), (mode, result)
                reply = await execute(
                    docker.portal,
                    "import urllib.request,json; print(json.dumps(urllib.request.urlopen('http://"
                    + game_ip
                    + ":6084', timeout=3).status))",
                )
                assert reply == 200, reply
                inbound = await execute(
                    canary,
                    "TARGETS=" + repr([("desktop", game_ip, 6084)]) + "\n" + probe,
                )
                assert not inbound["desktop"], inbound
                extra = await execute(
                    docker.portal,
                    "TARGETS=" + repr([("extra_port", game_ip, 7000)]) + "\n" + probe,
                )
                assert not extra["extra_port"], extra
                await docker.request(
                    "POST",
                    "/networks/gamedock-session-" + sid + "/disconnect",
                    {"Container": docker.portal},
                )
                await docker.ensure_connection(sid)
                reconnected = await docker.request(
                    "GET", "/networks/gamedock-session-" + sid
                )
                restored = next(
                    c["IPv4Address"].split("/")[0]
                    for c in reconnected["Containers"].values()
                    if c["Name"] == docker.portal
                )
                assert restored == portal_ip, (restored, portal_ip)
                reachable = await execute(
                    docker.portal,
                    "import urllib.request,json; print(json.dumps([urllib.request.urlopen('http://"
                    + canary_ip
                    + ":'+str(p),timeout=3).status for p in (9000,9001)]))",
                )
                assert reachable == [200, 200], reachable
                print(
                    "PASS",
                    case,
                    ": Internet policy, local/portal/host/metadata/IPv6 block, reverse desktop reply, scoped exception",
                    flush=True,
                )
            finally:
                await docker.request(
                    "DELETE", "/containers/" + canary + "?force=true", missing=True
                )
                await docker.stop(sid)
                await docker.request(
                    "DELETE",
                    "/volumes/" + docker.namespace + "-user-999998-" + sid,
                    missing=True,
                )


asyncio.run(main())
