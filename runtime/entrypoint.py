#!/usr/bin/env python3
"""Generic desktop extracted from the Xvfb/Xpra session model."""

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time


from gpu import prepare_command, configure_software
from streaming import runtime_options, validate_streaming


def resolution(value):
    if not re.fullmatch(r"[0-9]{3,4}x[0-9]{3,4}", value):
        raise ValueError("Resolution must be WIDTHxHEIGHT")
    width, height = map(int, value.split("x"))
    if not (640 <= width <= 3840 and 480 <= height <= 2160):
        raise ValueError("Resolution out of bounds")
    return value


def main():
    size = resolution(os.environ.get("GAMEDOCK_RESOLUTION", "1280x720"))
    command = sys.argv[1:]
    if not command:
        raise ValueError("A game command is required")
    runtime = os.environ["XDG_RUNTIME_DIR"]
    os.makedirs(runtime, mode=0o700, exist_ok=True)
    settings = validate_streaming(
        json.loads(os.environ.get("GAMEDOCK_STREAMING", "{}")), complete=True
    )
    xpra_args, xpra_env = runtime_options(settings)
    # Set before Xpra imports its capture, socket, and batching modules.
    os.environ.update(xpra_env)
    # Per-session HTML defaults keep client quality requests consistent with the server.
    html_dir = Path(runtime) / "html"
    html_dir.mkdir(exist_ok=True)
    source = Path("/usr/share/xpra/www")
    for entry in source.iterdir():
        if entry.name.startswith("default-settings.txt"):
            continue
        target = html_dir / entry.name
        if not target.exists():
            target.symlink_to(entry)
    defaults = (
        (source / "default-settings.txt").read_text()
        if (source / "default-settings.txt").exists()
        else ""
    )
    defaults += (
        "\n"
        + "\n".join(
            key.replace("_", "-") + " = " + str(settings[key])
            for key in ("encoding", "quality", "min_quality", "speed", "min_speed")
        )
        + "\n"
    )
    (html_dir / "default-settings.txt").write_text(defaults)
    configure_software()
    children = []

    def stop(*_):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        children.append(
            subprocess.Popen(
                [
                    "Xvfb",
                    ":0",
                    "-screen",
                    "0",
                    size + "x24",
                    "-nolisten",
                    "tcp",
                    "-noreset",
                ]
            )
        )
        deadline = time.monotonic() + 20
        while subprocess.run(
            ["xdpyinfo"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode:
            if children[0].poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("Desktop failed to start")
            time.sleep(0.1)
        command, gpu_info = prepare_command(command)
        (Path(runtime) / "gpu.json").write_text(json.dumps(gpu_info))
        print("GameDock graphics: " + json.dumps(gpu_info), flush=True)
        children.append(subprocess.Popen(["openbox"]))
        children.append(
            subprocess.Popen(
                [
                    "xpra",
                    "shadow",
                    ":0",
                    "--daemon=no",
                    "--bind-tcp=0.0.0.0:6084",
                    "--html=" + str(html_dir),
                    "--mdns=no",
                    "--pulseaudio=no",
                    "--notifications=no",
                ]
                + xpra_args
            )
        )
        children.append(subprocess.Popen(command, cwd="/data"))
        while all(child.poll() is None for child in children):
            time.sleep(0.25)
        return next(
            (child.returncode for child in children if child.returncode is not None), 1
        )
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    sys.exit(main())
