#!/usr/bin/env python3
"""Generic desktop extracted from the Xvfb/Xpra session model."""
import os
import re
import signal
import subprocess
import sys
import time

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
    children = []
    def stop(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        children.append(subprocess.Popen(["Xvfb", ":0", "-screen", "0", size+"x24",
                                         "-nolisten", "tcp", "-noreset"]))
        deadline = time.monotonic() + 20
        while subprocess.run(["xdpyinfo"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL).returncode:
            if children[0].poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("Desktop failed to start")
            time.sleep(.1)
        children.append(subprocess.Popen(["openbox"]))
        children.append(subprocess.Popen(["xpra", "shadow", ":0", "--daemon=no",
                       "--bind-tcp=0.0.0.0:6084", "--html=on", "--mdns=no",
                       "--pulseaudio=no", "--notifications=no"]))
        children.append(subprocess.Popen(command, cwd="/data"))
        while all(child.poll() is None for child in children):
            time.sleep(.25)
        return next((child.returncode for child in children if child.returncode is not None), 1)
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
