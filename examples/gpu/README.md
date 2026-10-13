# GPU-accelerated GameDock runtimes (Linux)

Three targets are provided: `gamedock-runtime-gpu-nvidia:local`,
`gamedock-runtime-gpu-amd:local` and `gamedock-runtime-gpu-intel:local`.
Build on the Linux Docker host that has the GPU (and its CPU architecture):

```sh
./scripts/build-gpu.sh
```

The base runtime uses Mesa llvmpipe software OpenGL by default. It sets
`LIBGL_ALWAYS_SOFTWARE=1`, `GALLIUM_DRIVER=llvmpipe` and a quota-aware
`LP_NUM_THREADS` before starting the display and the game. No wrapper is added
to the CPU game's command. `gpu: {"vendor":"none","software_threads":0}`
selects automatic workers (CPU affinity and cgroup quota, capped at 16); an
explicit value from 1 to 64 is available in the game form. Fractional CPU quotas
still use one worker. Explicit overrides can exceed the quota; this does not
allocate additional CPU time. Increase Game CPU separately when needed.
The actual llvmpipe renderer and worker count are visible in Diagnostics.
Software OpenGL is available on this Mac's Linux containers, but uses CPU only.
The default does not enable a software Vulkan renderer or accelerate 2D drawing.

The base runtime remains CPU-only by default. GPU images add VirtualGL, Mesa,
GLVND and OpenGL/Vulkan diagnostic tools. They keep the existing unprivileged
UID/GID 1000:1000, Xvfb display and Selkies streaming. NVIDIA games use VirtualGL's EGL backend; AMD/Intel can use native DRI3/GLAMOR. VirtualGL's proxy
transport does not introduce a second lossy compression step.

This accelerates compatible **GLX/OpenGL games**. It does not turn every 2D game,
Vulkan/DirectX title or Windows application into a GPU-accelerated application.
Native Vulkan or Wine/DXVK presentation requires separate application-specific
validation. Installing Vulkan tools is not a claim that Vulkan display works.
Legacy 32-bit games require matching 32-bit VirtualGL and graphics libraries;
these variants include the native-architecture libraries only.
Video encoding is separate from rendering. Selkies/pixelflux can select VAAPI or
NVENC when supported by the selected device, libraries and host drivers. Verify
the actual encoder in Diagnostics/logs; mapping a GPU alone proves nothing about
encoding. There is no VRAM quota or exclusive reservation: sessions share GPU
resources. AMD/Intel use native DRI3/GLAMOR when supported; NVIDIA uses VirtualGL.

## NVIDIA host

Install the proprietary NVIDIA driver and NVIDIA Container Toolkit on the
**Linux host**, following the vendor's instructions:
https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
Configure its Docker runtime. Do not install a kernel driver in the image.
Verify host `nvidia-smi` first, then build the images and run:

```sh
GPU_ID=0 docker compose -p gamedock-gpu-demo -f examples/gpu/compose.yaml --profile nvidia up -d nvidia
# Desktop demo: http://localhost:6085
GPU_ID=0 docker compose -p gamedock-gpu-demo -f examples/gpu/compose.yaml run --rm --no-deps --entrypoint python3 nvidia /usr/local/bin/gpu.py
```

`GPU_ID` accepts an index or `GPU-...` UUID. The container receives only that
GPU. The injected driver capabilities are `graphics,utility,video`; CUDA is not
required for this rendering path. `egl0` selects the first visible EGL device.
If the host's enumeration requires another EGL index, set `gpu.vgl_display` in
the game profile and verify the reported renderer.

## AMD or Intel host

Use Linux's `amdgpu` driver for supported AMD GPUs or the appropriate `i915`/`xe`
driver for Intel. Find the correct render node and its numeric owning group:

```sh
ls -l /dev/dri/renderD*
export GPU_RENDER_DEVICE=/dev/dri/renderD128
export GPU_RENDER_GID=$(stat -c '%g' "$GPU_RENDER_DEVICE")
docker compose -p gamedock-gpu-demo -f examples/gpu/compose.yaml --profile amd up -d amd
# AMD desktop: http://localhost:6086
# Or replace amd with intel; Intel desktop: http://localhost:6087
docker compose -p gamedock-gpu-demo -f examples/gpu/compose.yaml run --rm --no-deps --entrypoint python3 amd /usr/local/bin/gpu.py
```

On multi-GPU hosts, select the node belonging to the intended vendor. The
example's group fallback of 109 is only a placeholder; always set the real GID.
Only this render node is mapped, with read/write access. No card control node,
privileged mode, host X socket or root user is needed for this EGL backend.
Hosts using SELinux or rootless Docker may require host-specific device access
configuration; do not solve permission errors by making the container privileged.

## Use from the GameDock administrator

Under **Games**, paste the corresponding `nvidia.json`, `amd.json` or `intel.json`
as a new game's JSON definition. The form also exposes vendor, device and host
GIDs. For AMD/Intel, replace `groups: []` with the numeric render node group, for
example `groups: [109]`. Changes apply to new sessions only.

The example games run `glxgears`. For your real game, derive its image from the
matching GPU runtime, install/copy the game, and set its normal command:

```dockerfile
FROM gamedock-runtime-gpu-amd:local
USER root
# Install your game's dependencies and files here.
USER 1000:1000
CMD ["/opt/my-game/start"]
```

The existing OpenTTD, Minecraft and Wine example Dockerfiles also accept
`BASE_IMAGE`, for example:

```sh
docker build --build-arg BASE_IMAGE=gamedock-runtime-gpu-amd:local -t gamedock-openttd-gpu-amd:local examples/openttd
```

This makes an image with the GPU runtime, but a 2D game such as OpenTTD may not
benefit from OpenGL acceleration. Keep that game image name in the profile. GPU access is applied to GameDock's
**dynamically created game containers**, not to the portal. The portal itself
does not need `--gpus` or `/dev/dri`.

At startup the runtime runs `vglrun -d <device> -c proxy glxinfo -B`. It requires
an actual renderer matching the selected vendor and rejects llvmpipe, softpipe,
swrast, SwiftShader and other recognized software renderers. Missing devices,
permissions, packages or drivers stop the session with an explicit Docker log
error; there is no silent CPU fallback. A successful result is logged and saved
to `/tmp/gamedock-runtime/gpu.json`. The player Diagnostics panel reports the
validated GPU vendor and OpenGL renderer. This proves the rendering path is
available; application-specific GPU usage still depends on the game.

```sh
docker logs gamedock-<instance-id>
docker exec gamedock-<instance-id> cat /tmp/gamedock-runtime/gpu.json
# Stop only these standalone demos:
docker compose -p gamedock-gpu-demo -f examples/gpu/compose.yaml down
```

Demo Selkies ports are unauthenticated and bound to localhost for testing. Use the
GameDock portal's authenticated sessions for players.

## Validation limits

The three images can be built on Apple Silicon, but **OrbStack does not expose
the Mac GPU to these Linux containers**. A successful image build is not a GPU
test. NVIDIA, AMD and Intel hardware rendering must be verified on compatible
Linux hosts using the commands above. Do not expect `--gpus` or a Dockerfile to
provide Apple GPU passthrough.

References:
- VirtualGL EGL backend: https://github.com/VirtualGL/virtualgl/blob/main/doc/advancedconfig.txt
- NVIDIA driver capabilities: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/docker-specialized.html
- Mesa supported platforms: https://docs.mesa3d.org/systems.html
- OrbStack limitations: https://docs.orbstack.dev/faq#what-cant-you-do
