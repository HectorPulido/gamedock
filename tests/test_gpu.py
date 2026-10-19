"""GPU access, validation and rejection of misleading software renderers."""

import unittest
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
import os
from runtime.gpu import (
    validate_gpu,
    docker_gpu,
    renderer_info,
    prepare_command,
    software_thread_count,
)
from server.app import Docker, validate_profile


class GPU(unittest.TestCase):
    def test_device_access_keeps_vendor_and_permissions_explicit(self):
        host, env = docker_gpu({"vendor": "nvidia", "device": "GPU-abcd-123"})
        self.assertEqual(host["DeviceRequests"][0]["DeviceIDs"], ["GPU-abcd-123"])
        self.assertEqual(host["DeviceRequests"][0]["Capabilities"], [["gpu"]])
        self.assertIn("NVIDIA_DRIVER_CAPABILITIES=graphics,utility,video", env)
        for vendor in ("amd", "intel"):
            host, _ = docker_gpu(
                {
                    "vendor": vendor,
                    "device": "/dev/dri/renderD129",
                    "groups": [109, 109],
                }
            )
            self.assertEqual(
                host["Devices"],
                [
                    {
                        "PathOnHost": "/dev/dri/renderD129",
                        "PathInContainer": "/dev/dri/renderD129",
                        "CgroupPermissions": "rw",
                    }
                ],
            )
            self.assertEqual(host["GroupAdd"], ["109"])
            self.assertNotIn("DeviceRequests", host)
        self.assertEqual(docker_gpu({})[0], {})
        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "runtime.gpu.subprocess.run",
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout="OpenGL renderer string: llvmpipe (LLVM 21)",
                    stderr="",
                ),
            ),
        ):
            command, info = prepare_command(["xterm"], {"software_threads": 3})
            self.assertEqual(command, ["xterm"])
            self.assertEqual(info["software_threads"], 3)
            self.assertEqual(os.environ["GALLIUM_DRIVER"], "llvmpipe")
            self.assertFalse(info["enabled"])

    def test_automatic_workers_follow_cgroup_quota_and_affinity(self):
        with (
            patch(
                "runtime.gpu.os.sched_getaffinity",
                return_value=set(range(32)),
                create=True,
            ),
            patch("runtime.gpu.Path.read_text", return_value="200000 100000"),
        ):
            self.assertEqual(software_thread_count(), 2)
            self.assertEqual(software_thread_count(6), 6)
        with (
            patch("runtime.gpu.os.sched_getaffinity", return_value={0}, create=True),
            patch("runtime.gpu.Path.read_text", return_value="max 100000"),
        ):
            self.assertEqual(software_thread_count(), 1)
        for value in (-1, 65, True, "4"):
            with self.assertRaises(ValueError):
                validate_gpu({"software_threads": value})

    def test_invalid_device_paths_groups_and_vendor(self):
        for value in (
            None,
            [],
            {"vendor": "apple"},
            {"vendor": []},
            {"vendor": "amd", "device": "/dev/sda"},
            {"vendor": "nvidia", "device": "all"},
            {"vendor": "intel", "groups": [True]},
            {"vendor": "intel", "groups": [0]},
            {"vendor": "none", "device": "0"},
            {"vendor": "amd", "vgl_display": ":0"},
            {"vendor": "amd", "vgl_display": "/dev/dri/renderD129"},
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_gpu(value)

    def test_hardware_renderer_must_match_requested_vendor(self):
        for vendor, renderer in (
            ("amd", "AMD Radeon RX 6600"),
            ("intel", "Mesa Intel(R) UHD Graphics 630"),
            ("nvidia", "NVIDIA GeForce RTX 3060/PCIe/SSE2"),
        ):
            self.assertTrue(
                renderer_info("OpenGL renderer string: " + renderer, vendor)["enabled"]
            )
        for renderer in (
            "llvmpipe (LLVM 20.1)",
            "softpipe",
            "Software Rasterizer",
            "",
            "NVIDIA RTX 3060",
        ):
            with self.subTest(renderer=renderer), self.assertRaises(RuntimeError):
                renderer_info("OpenGL renderer string: " + renderer, "intel")
        with (
            patch("runtime.gpu.shutil.which", return_value=None),
            self.assertRaisesRegex(RuntimeError, "requires a gamedock-runtime-gpu"),
        ):
            prepare_command(["game"], {"vendor": "nvidia"})


class DockerGPU(unittest.IsolatedAsyncioTestCase):
    async def test_payload_and_legacy_profiles(self):
        for vendor in ("none", "nvidia", "amd", "intel"):
            profile = validate_profile(
                {
                    "id": "test",
                    "name": "Test",
                    "image": "gpu:local",
                    "command": ["glxgears"],
                    "gpu": {"vendor": vendor},
                }
            )
            profile.update(memory_mb=1024, cpus=1)
            docker = Docker()

            async def response(method, path, *args, **kwargs):
                if path.endswith("/json"):
                    return {"State": {"Running": True, "Health": {"Status": "healthy"}}}
                return {}

            docker.request = AsyncMock(side_effect=response)
            await docker.start("test", 1, profile, "1280x720")
            payload = next(
                c.args[2]
                for c in docker.request.call_args_list
                if "/containers/create?name=gamedock-test" == c.args[1]
            )
            self.assertEqual(payload["HostConfig"]["CapDrop"], ["ALL"])
            self.assertNotIn("Privileged", payload["HostConfig"])
            self.assertTrue(any(s.startswith("GAMEDOCK_GPU=") for s in payload["Env"]))
            self.assertEqual(
                "DeviceRequests" in payload["HostConfig"], vendor == "nvidia"
            )
            self.assertEqual(
                "Devices" in payload["HostConfig"], vendor in ("amd", "intel")
            )


class StandaloneGPUProbe(unittest.TestCase):
    def test_amd_and_intel_use_native_dri_without_virtualgl(self):
        from runtime import gpu as module
        from unittest.mock import MagicMock
        for vendor, renderer in (("amd", "AMD Radeon Graphics"), ("intel", "Intel Iris Graphics")):
            profile = validate_gpu({"vendor": vendor, "device": "/dev/dri/renderD129"})
            display = MagicMock()
            probe = SimpleNamespace(returncode=0, stderr="", stdout="OpenGL vendor string: " + vendor + "\nOpenGL renderer string: " + renderer + "\nOpenGL version string: 4.6\n")
            with patch.object(module, "configured_gpu", return_value=profile), patch.object(module, "configure_software"), patch.object(module.subprocess, "Popen", return_value=display) as spawn, patch.object(module.subprocess, "run", return_value=probe) as run, patch.object(module, "prepare_command") as vgl:
                self.assertEqual(module.main(), 0)
                self.assertEqual(spawn.call_args.args[0][-3:], ["-glamor", "-dri", "/dev/dri/renderD129"])
                self.assertEqual(run.call_args.args[0], ["glxinfo", "-B"])
                vgl.assert_not_called()
                display.terminate.assert_called_once()
