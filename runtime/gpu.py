"""GPU profile validation, Docker access and verified VirtualGL rendering."""

import json
import math
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys

VENDORS = ("none", "nvidia", "amd", "intel")


def validate_gpu(value):
    if not isinstance(value, dict) or set(value) - {
        "vendor",
        "device",
        "groups",
        "vgl_display",
        "software_threads",
    }:
        raise ValueError(
            "GPU: expected vendor, device, groups, vgl_display or software_threads"
        )
    vendor = value.get("vendor", "none")
    if vendor not in VENDORS:
        raise ValueError("GPU vendor must be none, nvidia, amd or intel")
    if vendor == "none":
        if set(value) - {"vendor", "software_threads"}:
            raise ValueError("GPU: remove device options when acceleration is disabled")
        threads = value.get("software_threads", 0)
        if type(threads) is not int or not 0 <= threads <= 64:
            raise ValueError(
                "CPU rendering threads must be between 0 (automatic) and 64"
            )
        return {"vendor": "none", "software_threads": threads}
    if "software_threads" in value:
        raise ValueError("CPU rendering threads apply only to the CPU graphics profile")
    device = value.get("device", "0" if vendor == "nvidia" else "/dev/dri/renderD128")
    pattern = (
        r"(?:[0-9]{1,3}|GPU-[a-zA-Z0-9-]{1,80})"
        if vendor == "nvidia"
        else r"/dev/dri/renderD[0-9]{3,5}"
    )
    if not isinstance(device, str) or not re.fullmatch(pattern, device):
        raise ValueError(
            "GPU device: use an NVIDIA index/UUID or /dev/dri/renderD128 for AMD/Intel"
        )
    groups = value.get("groups", [])
    if (
        not isinstance(groups, list)
        or len(groups) > 8
        or any(type(g) is not int or not 1 <= g <= 2147483647 for g in groups)
    ):
        raise ValueError("GPU groups must contain up to eight positive host group IDs")
    display = value.get("vgl_display", "egl0" if vendor == "nvidia" else device)
    if not isinstance(display, str) or not re.fullmatch(
        r"egl[0-9]{0,3}|/dev/dri/renderD[0-9]{3,5}", display
    ):
        raise ValueError("VirtualGL display must be egl, egl0 or a render device path")
    if vendor != "nvidia" and display != device:
        raise ValueError(
            "AMD/Intel VirtualGL display must match the mapped render device"
        )
    return {
        "vendor": vendor,
        "device": device,
        "groups": list(dict.fromkeys(groups)),
        "vgl_display": display,
    }


def docker_gpu(value):
    """Access is limited to the selected device, keeping the unprivileged user."""
    gpu = validate_gpu(value)
    host = {}
    env = ["GAMEDOCK_GPU=" + json.dumps(gpu)]
    if gpu["vendor"] == "nvidia":
        host["DeviceRequests"] = [
            {
                "Driver": "nvidia",
                "DeviceIDs": [gpu["device"]],
                "Capabilities": [["gpu"]],
                "Options": {},
            }
        ]
        env += ["NVIDIA_DRIVER_CAPABILITIES=graphics,utility,video"]
    elif gpu["vendor"] in ("amd", "intel"):
        host["Devices"] = [
            {
                "PathOnHost": gpu["device"],
                "PathInContainer": gpu["device"],
                "CgroupPermissions": "rw",
            }
        ]
    if gpu.get("groups"):
        host["GroupAdd"] = [str(group) for group in gpu["groups"]]
    return host, env


def configured_gpu():
    return validate_gpu(json.loads(os.environ.get("GAMEDOCK_GPU", "{}")))


def renderer_info(text, vendor):
    fields = {}
    for key in (
        "OpenGL vendor string",
        "OpenGL renderer string",
        "OpenGL version string",
    ):
        match = re.search(r"^\s*" + re.escape(key) + r":\s*(.+)$", text, re.M)
        if match:
            fields[key.split()[1]] = match[1].strip()
    renderer = fields.get("renderer", "")
    if not renderer or re.search(
        r"llvmpipe|softpipe|swrast|software rasterizer|swiftshader", renderer, re.I
    ):
        raise RuntimeError(
            "GPU check failed: no hardware OpenGL renderer detected ("
            + (renderer or "missing renderer")
            + ")"
        )
    identity = fields.get("vendor", "") + " " + renderer
    expected = {"nvidia": r"NVIDIA", "amd": r"AMD|ATI|Radeon", "intel": r"Intel"}[
        vendor
    ]
    if not re.search(expected, identity, re.I):
        raise RuntimeError(
            "GPU check failed: renderer does not match " + vendor + ": " + identity
        )
    return {
        "enabled": True,
        "vendor": vendor,
        "renderer": renderer,
        "opengl_version": fields.get("version", ""),
    }


def software_thread_count(override=0):
    if override:
        return override
    try:
        count = len(os.sched_getaffinity(0))
    except AttributeError:
        count = os.cpu_count() or 1
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            count = min(count, max(1, math.ceil(int(quota) / int(period))))
    except (OSError, ValueError, ZeroDivisionError):
        try:
            quota = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
            period = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
            if quota > 0 and period > 0:
                count = min(count, max(1, math.ceil(quota / period)))
        except (OSError, ValueError):
            pass
    return max(1, min(count, 16))


def configure_software(gpu=None):
    gpu = configured_gpu() if gpu is None else validate_gpu(gpu)
    if gpu["vendor"] == "none":
        threads = software_thread_count(gpu["software_threads"])
        os.environ.update(
            {
                "LIBGL_ALWAYS_SOFTWARE": "1",
                "GALLIUM_DRIVER": "llvmpipe",
                "__GLX_VENDOR_LIBRARY_NAME": "mesa",
                "LP_NUM_THREADS": str(threads),
            }
        )
        return threads
    return None


def prepare_command(command, gpu=None):
    gpu = configured_gpu() if gpu is None else validate_gpu(gpu)
    if gpu["vendor"] == "none":
        threads = configure_software(gpu)
        probe = subprocess.run(
            ["glxinfo", "-B"], capture_output=True, text=True, timeout=30
        )
        renderer = re.search(r"^\s*OpenGL renderer string:\s*(.+)$", probe.stdout, re.M)
        if probe.returncode or not renderer or "llvmpipe" not in renderer[1].lower():
            raise RuntimeError(
                "CPU OpenGL check failed: " + (probe.stderr or probe.stdout)[-2000:]
            )
        return command, {
            "enabled": False,
            "vendor": "none",
            "mode": "software",
            "renderer": renderer[1].strip(),
            "software_threads": threads,
        }
    image_vendor = os.environ.get("GAMEDOCK_GPU_VENDOR")
    if image_vendor and image_vendor != gpu["vendor"]:
        raise RuntimeError("GPU profile and runtime image vendor do not match")
    vgl = shutil.which("vglrun")
    if not vgl or not shutil.which("glxinfo"):
        raise RuntimeError(
            "GPU support requires a gamedock-runtime-gpu-" + gpu["vendor"] + " image"
        )
    if gpu["vendor"] in ("amd", "intel") and not os.access(
        gpu["device"], os.R_OK | os.W_OK
    ):
        raise RuntimeError(
            "GPU render device is missing or inaccessible: "
            + gpu["device"]
            + ". Map the device and add its host group ID to gpu.groups."
        )
    prefix = [vgl, "-d", gpu["vgl_display"], "-c", "proxy"]
    probe = subprocess.run(
        prefix + ["glxinfo", "-B"], capture_output=True, text=True, timeout=30
    )
    if probe.returncode:
        raise RuntimeError(
            "GPU OpenGL check failed: " + (probe.stderr or probe.stdout)[-2000:]
        )
    info = renderer_info(probe.stdout, gpu["vendor"])
    info["device"] = gpu["device"]
    return prefix + command, info


def main():
    """Standalone check starts an isolated display; runtime uses prepare_command."""
    import time

    os.environ["DISPLAY"] = ":99"
    display = subprocess.Popen(
        ["Xvfb", ":99", "-screen", "0", "640x480x24", "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            if (
                subprocess.run(
                    ["xdpyinfo"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                ).returncode
                == 0
            ):
                break
            if display.poll() is not None:
                raise RuntimeError("GPU test display failed to start")
            time.sleep(0.1)
        else:
            raise RuntimeError("GPU test display timed out")
        _, info = prepare_command(["true"])
        print(json.dumps(info))
        return 0
    except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"enabled": False, "error": str(error)}))
        return 1
    finally:
        display.terminate()
        display.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
